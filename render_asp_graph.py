#!/usr/bin/env python3
"""Render ASP dungeon facts to a PNG using Graphviz.

Expected facts file: one atom per token, such as:
- node(X)
- paft(A,B)
- taft(K,L)
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess


ATOM_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)\((.*)\)$")


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


def parse_atom(token: str) -> tuple[str, list[str]] | None:
    token = token.strip().rstrip(".")
    if not token:
        return None
    m = ATOM_RE.match(token)
    if not m:
        return None
    pred = m.group(1)
    args = split_top_level_args(m.group(2))
    return pred, args


def parse_facts(path: Path) -> tuple[set[str], list[tuple[str, str]], list[tuple[str, str]]]:
    text = path.read_text()
    tokens = text.split()
    nodes: set[str] = set()
    paft: list[tuple[str, str]] = []
    taft: list[tuple[str, str]] = []

    for token in tokens:
        parsed = parse_atom(token)
        if parsed is None:
            continue
        pred, args = parsed
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

    return nodes, paft, taft


def node_style(node: str) -> str:
    if node == "start":
        return 'shape=oval, style="filled", fillcolor="#c7f9cc", color="#2d6a4f"'
    if node == "boss":
        return 'shape=doubleoctagon, style="filled", fillcolor="#ffccd5", color="#9d0208"'
    if node.startswith("sk(") or node.startswith("bk(") or node.startswith("di("):
        return 'shape=diamond, style="filled", fillcolor="#fff3bf", color="#8d6e00"'
    if node.startswith("sl(") or node.startswith("dl(") or node.startswith("bl("):
        return 'shape=box, style="filled", fillcolor="#dbe4ff", color="#2b2d42"'
    return 'shape=ellipse, color="#495057"'


def write_dot(path: Path, nodes: set[str], paft: list[tuple[str, str]], taft: list[tuple[str, str]]) -> None:
    lines: list[str] = []
    lines.append("digraph dungeon {")
    lines.append("  rankdir=TB;")
    lines.append('  graph [bgcolor="white"];')
    lines.append('  node [fontname="Helvetica", fontsize=10];')
    lines.append('  edge [fontname="Helvetica", fontsize=9];')

    for n in sorted(nodes):
        lines.append(f'  "{n}" [{node_style(n)}];')

    for a, b in paft:
        if a == b:
            continue
        lines.append(f'  "{a}" -> "{b}" [color="#111111", penwidth=1.7, label="paft"];')

    for k, l in taft:
        lines.append(
            f'  "{k}" -> "{l}" [style=dashed, color="#6c757d", penwidth=1.2, label="taft"];'
        )

    lines.append("}")
    path.write_text("\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render ASP graph facts as a PNG image.")
    p.add_argument("--facts", type=Path, default=Path("asp_generated_dungeon_facts.txt"), help="Input facts file.")
    p.add_argument("--out-dot", type=Path, default=Path("asp_generated_dungeon_graph.dot"), help="Output DOT file.")
    p.add_argument("--out-png", type=Path, default=Path("asp_generated_dungeon_graph.png"), help="Output PNG file.")
    p.add_argument("--dot-bin", type=str, default="dot", help="Graphviz dot executable.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    nodes, paft, taft = parse_facts(args.facts)
    write_dot(args.out_dot, nodes, paft, taft)

    cmd = [args.dot_bin, "-Tpng", str(args.out_dot), "-o", str(args.out_png)]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"dot failed with code {proc.returncode}:\n{proc.stderr}\n{proc.stdout}")

    print(f"DOT: {args.out_dot}")
    print(f"PNG: {args.out_png}")
    print(f"Nodes: {len(nodes)}")
    print(f"paft edges: {len([1 for a, b in paft if a != b])}")
    print(f"taft edges: {len(taft)}")


if __name__ == "__main__":
    main()
