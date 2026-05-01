#!/usr/bin/env python3
"""Generate an ASP dungeon graph with clingo, then validate solvability.

Pipeline:
1) Run clingo on an ASP encoding to get one answer set.
2) Convert paft/taft atoms into an abstract graph with lock/key semantics.
3) Reuse solve_with_abstract_graph from tile_level_bfs_solver.py.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import resource
import subprocess

from tile_level_bfs_solver import solve_with_abstract_graph


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate ASP dungeon graph and validate solvability.")
    p.add_argument(
        "--encoding",
        type=Path,
        default=Path("asp/dungeon_generator.lp"),
        help="Path to ASP encoding (.lp).",
    )
    p.add_argument(
        "--output-prefix",
        type=str,
        default="asp_generated_dungeon",
        help="Output prefix for facts and graph JSON.",
    )
    p.add_argument(
        "--clingo-bin",
        type=str,
        default="clingo",
        help="Clingo executable to invoke.",
    )
    p.add_argument(
        "--const",
        action="append",
        default=[],
        help="Repeatable clingo constant override, e.g. --const min_boss_depth=8.",
    )
    p.add_argument(
        "--time-limit",
        type=int,
        default=60,
        help="Wall-clock timeout for clingo in seconds (0 disables timeout).",
    )
    p.add_argument(
        "--memory-limit-mb",
        type=int,
        default=2048,
        help="Address-space cap for clingo in MB on POSIX (0 disables limit).",
    )
    p.add_argument(
        "--threads",
        type=int,
        default=1,
        help="Number of clingo solver threads.",
    )
    return p.parse_args()


def split_top_level_args(arg_blob: str) -> list[str]:
    args: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in arg_blob:
        if ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        cur.append(ch)
    if cur:
        args.append("".join(cur).strip())
    return args


def parse_atom(atom: str) -> tuple[str, list[str]]:
    atom = atom.strip()
    if "(" not in atom:
        return atom, []
    pred, rest = atom.split("(", 1)
    if not rest.endswith(")"):
        raise ValueError(f"Malformed atom: {atom}")
    args = split_top_level_args(rest[:-1])
    return pred.strip(), args


def _preexec_resource_limits(memory_limit_mb: int, cpu_limit_seconds: int):
    def _apply() -> None:
        if memory_limit_mb > 0:
            limit_bytes = memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        if cpu_limit_seconds > 0:
            # Slightly above wall timeout to avoid early CPU-only termination.
            cpu_hard = cpu_limit_seconds + 2
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_hard, cpu_hard))

    return _apply


def run_clingo(
    encoding_path: Path,
    clingo_bin: str,
    const_overrides: list[str],
    time_limit: int,
    memory_limit_mb: int,
    threads: int,
) -> list[str]:
    cmd = [clingo_bin, str(encoding_path), "-n", "1", "--outf=2", "-t", str(max(1, threads))]
    for const_override in const_overrides:
        cmd.extend(["-c", const_override])

    kwargs: dict = {
        "check": False,
        "capture_output": True,
        "text": True,
    }
    if time_limit > 0:
        kwargs["timeout"] = time_limit

    is_posix = platform.system() != "Windows"
    if is_posix and memory_limit_mb > 0:
        kwargs["preexec_fn"] = _preexec_resource_limits(memory_limit_mb, time_limit)

    try:
        proc = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"clingo timed out after {time_limit}s. Try lowering constraints, "
            "using fewer nodes, or raising --time-limit."
        ) from exc

    if proc.returncode not in (10, 30):
        resource_hint = ""
        if is_posix and memory_limit_mb > 0 and proc.returncode in (-9, 137, 134):
            resource_hint = (
                "\nLikely resource cap hit (memory/time). "
                "Try lowering generation constants or increasing --memory-limit-mb/--time-limit."
            )
        raise RuntimeError(
            f"clingo failed (code {proc.returncode}):\n{proc.stderr}\n{proc.stdout}{resource_hint}"
        )

    payload = json.loads(proc.stdout)
    calls = payload.get("Call", [])
    if not calls:
        raise RuntimeError("clingo returned no Call entries.")
    witnesses = calls[0].get("Witnesses", [])
    if not witnesses:
        raise RuntimeError("No ASP model found (unsatisfiable for this encoding/configuration).")
    return witnesses[0].get("Value", [])


def facts_to_graph(atoms: list[str]) -> tuple[dict, list[str]]:
    nodes: set[str] = set()
    paft: list[tuple[str, str]] = []
    taft: list[tuple[str, str]] = []

    for atom in atoms:
        pred, args = parse_atom(atom)
        if pred == "node" and len(args) == 1:
            nodes.add(args[0])
        elif pred == "paft" and len(args) == 2:
            paft.append((args[0], args[1]))
            nodes.add(args[0])
            nodes.add(args[1])
        elif pred == "taft" and len(args) == 2:
            taft.append((args[0], args[1]))
            nodes.add(args[0])
            nodes.add(args[1])

    # Convert physical tree relation to traversable graph edges. Use bidirectional
    # edges so backtracking is possible in the validation search.
    edges: list[list[str]] = []
    for a, b in paft:
        if a == b:
            continue
        edges.append([a, b])
        edges.append([b, a])

    node_items: dict[str, dict[str, int]] = {}
    node_requirements: dict[str, dict[str, dict[str, int]]] = {}

    for key, lock in taft:
        if key.startswith("sk("):
            node_items.setdefault(key, {})[key] = 1
            node_requirements[lock] = {"need": {key: 1}, "consume": {key: 1}}
        elif key.startswith("bk("):
            node_items.setdefault(key, {})[key] = 1
            node_requirements[lock] = {"need": {key: 1}, "consume": {key: 1}}
        elif key.startswith("di("):
            node_items.setdefault(key, {})[key] = 1
            node_requirements[lock] = {"need": {key: 1}, "consume": {}}
        else:
            node_items.setdefault(key, {})[key] = 1
            node_requirements[lock] = {"need": {key: 1}, "consume": {key: 1}}

    for n in nodes:
        if n.startswith("sk(") or n.startswith("bk(") or n.startswith("di("):
            node_items.setdefault(n, {})[n] = 1

    graph = {
        "start": "start",
        "goal": "boss",
        "edges": edges,
        "node_items": node_items,
        "node_requirements": node_requirements,
    }

    return graph, sorted(atoms)


def main() -> None:
    args = parse_args()

    try:
        atoms = run_clingo(
            args.encoding,
            args.clingo_bin,
            args.const,
            args.time_limit,
            args.memory_limit_mb,
            args.threads,
        )
    except RuntimeError as exc:
        raise SystemExit(f"Generation failed: {exc}") from exc

    graph, sorted_atoms = facts_to_graph(atoms)
    result = solve_with_abstract_graph(graph)

    prefix = args.output_prefix
    out_facts = Path(f"{prefix}_facts.txt")
    out_graph = Path(f"{prefix}_graph.json")

    out_facts.write_text("\n".join(sorted_atoms) + "\n")
    out_graph.write_text(json.dumps(graph, indent=2) + "\n")

    print(f"Encoding: {args.encoding}")
    if args.const:
        print(f"Constants: {args.const}")
    print(f"Clingo threads: {args.threads}")
    print(f"Clingo time limit: {args.time_limit}s")
    print(f"Clingo memory limit: {args.memory_limit_mb}MB")
    print(f"Facts written: {out_facts}")
    print(f"Graph written: {out_graph}")
    print(f"Solvable: {result['solvable']}")
    print(f"Visited states: {result.get('visited_states')}")
    if result["solvable"]:
        print(f"Moves: {result['moves']}")
        print(f"Path: {result['path']}")
    else:
        print(f"Reason: {result.get('reason')}")


if __name__ == "__main__":
    main()
