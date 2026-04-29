#!/usr/bin/env python3
"""Run uncapped room-segmented BFS for universal branch validity.

This checks the normal objective universally:
- valid=True means every reachable branch can still reach a win state.
- valid=False means at least one reachable branch is unwinnable (soft lock).

Important: this run is intentionally uncapped. It relies on memoization in the
state graph traversal to terminate on finite levels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from graph_solver_scratch import load_level_by_number
from room_macro_micro_bfs_solver import validate_no_softlock_to_exit


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Uncapped room-segmented universal BFS validator.")
    p.add_argument(
        "--dat",
        type=Path,
        default=Path("./CCUP/Level Sets/CCLP1/data/CCLP1.dat"),
        help="Path to DAT file (used when --level-json is not provided).",
    )
    p.add_argument("--level", type=int, default=1, help="Level number in DAT.")
    p.add_argument(
        "--level-json",
        type=Path,
        default=None,
        help="Optional JSON level file to validate instead of DAT level.",
    )
    p.add_argument(
        "--show-counterexample",
        action="store_true",
        help="Print counterexample room sequence when validation fails.",
    )
    return p.parse_args()


def load_level(args: argparse.Namespace) -> dict:
    if args.level_json is not None:
        return json.loads(args.level_json.read_text())
    return load_level_by_number(args.dat, args.level)


def main() -> None:
    args = parse_args()
    level = load_level(args)

    result = validate_no_softlock_to_exit(level)
    title = "=== Uncapped Room-Segmented Universal BFS ==="

    print(title)
    if args.level_json is not None:
        print("Input:", args.level_json)
    else:
        print("Input:", args.dat, "level", args.level)

    print("Valid (all branches can still win):", result.get("valid"))
    print("Reason:", result.get("reason", "ok"))
    print("Expanded states:", result.get("expanded_states"))
    print("Unique reachable states:", result.get("state_count"))
    print("Winning states:", result.get("winning_state_count"))
    print("Goal states:", result.get("goal_state_count"))

    if args.show_counterexample and not result.get("valid"):
        print("Counterexample rooms:", result.get("counterexample_rooms"))


if __name__ == "__main__":
    main()
