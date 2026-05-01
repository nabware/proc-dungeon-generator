#!/usr/bin/env python3
"""Derive a true soft-lock Key Pyramid demo from the real DAT level.

The output preserves Key Pyramid geometry and changes only one key/lock tile,
creating a branch where the player can become unwinnable while another branch
still reaches the exit.
"""

from __future__ import annotations

import json
from pathlib import Path

from tile_level_bfs_solver import effective_tile_id, load_level_by_number, solve_with_chip_state
from level_renderer import render_level, render_level_to_path
from room_macro_micro_bfs_solver import (
    solve_two_graph_hierarchical,
    validate_all_solution_paths,
    validate_no_softlock_to_exit,
)

WIDTH = 32
HEIGHT = 32
TOTAL = WIDTH * HEIGHT

FLOOR = 0x00
RED_LOCK = 0x17
YELLOW_LOCK = 0x19

DAT_PATH = Path("./CCUP/Level Sets/CCLP1/data/CCLP1.dat")
OUTPUT_JSON = Path("generated_key_pyramid_soft_lock.json")
OUTPUT_MAP = Path("generated_key_pyramid_soft_lock_map.txt")
OUTPUT_PNG = Path("generated_key_pyramid_soft_lock.png")


def pos(x: int, y: int) -> int:
    return y * WIDTH + x


def render_ascii(level: dict) -> str:
    key_glyph = {0x64: "b", 0x65: "r", 0x66: "g", 0x67: "y"}
    lock_glyph = {0x16: "B", 0x17: "R", 0x18: "G", 0x19: "Y"}

    lines: list[str] = []
    for y in range(HEIGHT):
        row: list[str] = []
        for x in range(WIDTH):
            t = effective_tile_id(level, pos(x, y))
            if t == 0x01:
                row.append("#")
            elif t == 0x6C:
                row.append("S")
            elif t == 0x15:
                row.append("E")
            elif t == 0x02:
                row.append("C")
            elif t == 0x21:
                row.append("O")
            elif t in key_glyph:
                row.append(key_glyph[t])
            elif t in lock_glyph:
                row.append(lock_glyph[t])
            elif t == 0x03:
                row.append("~")
            elif t == 0x04:
                row.append("^")
            elif t == 0x0C:
                row.append("*")
            elif t == 0x0D:
                row.append(">")
            else:
                row.append(".")
        lines.append("".join(row))
    return "\n".join(lines)


def add_soft_lock_branch(level: dict) -> dict:
    """Mutate the real Key Pyramid level with a single key/lock recolor.

    This mutation was selected by searching for a level that remains solvable,
    but contains reachable states that can no longer reach a normal win.
    """
    mutated = json.loads(json.dumps(level))

    # Swap right-side locks so the center-right approach exposes two red locks.
    # Original tiles on Key Pyramid level 1:
    #   (16,16) = yellow lock (0x19)
    #   (18,16) = red lock (0x17)
    # After swap:
    #   (16,16) = red lock
    #   (18,16) = yellow lock
    left_x, left_y = 16, 16
    right_x, right_y = 18, 16
    left_idx = pos(left_x, left_y)
    right_idx = pos(right_x, right_y)

    # Keep lock tiles on layer1 and clear layer2 so effective tiles are locks.
    mutated["layer1"][left_idx] = RED_LOCK
    mutated["layer1"][right_idx] = YELLOW_LOCK
    mutated["layer2"][left_idx] = 0x00
    mutated["layer2"][right_idx] = 0x00

    return mutated


def main() -> None:
    base_level = load_level_by_number(DAT_PATH, 1)
    soft_lock_level = add_soft_lock_branch(base_level)

    OUTPUT_JSON.write_text(json.dumps(soft_lock_level, indent=2))
    OUTPUT_MAP.write_text(render_ascii(soft_lock_level) + "\n")
    render_level_to_path(soft_lock_level, OUTPUT_PNG, tile_size=24)

    tile_result = solve_with_chip_state(soft_lock_level)
    two_result = solve_two_graph_hierarchical(soft_lock_level, collect_all=False)
    softlock_result = validate_no_softlock_to_exit(soft_lock_level)
    universal_result = validate_all_solution_paths(soft_lock_level)

    print("Base level:", DAT_PATH)
    print("Soft-lock demo JSON:", OUTPUT_JSON)
    print("Soft-lock demo map:", OUTPUT_MAP)
    print("Soft-lock demo PNG:", OUTPUT_PNG)
    print("Tile solver solvable:", tile_result.get("solvable"), "moves:", tile_result.get("moves"))
    print("Two-graph normal-goal solvable:", two_result.get("solvable"), "moves:", two_result.get("moves"))
    print("Soft-lock validation (normal goal):", softlock_result.get("valid"), softlock_result.get("reason", "ok"))
    print("Collect-all branch validation:", universal_result.get("valid"), universal_result.get("reason", "ok"))


if __name__ == "__main__":
    main()
