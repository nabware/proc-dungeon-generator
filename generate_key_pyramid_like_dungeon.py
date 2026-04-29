#!/usr/bin/env python3
"""Generate a Key-Pyramid-like dungeon and verify it is solvable.

This script uses a constructive room skeleton with keys, locks, chips,
socket, and exit, then validates each candidate with:
1) tile solver (`solve_with_chip_state`)
2) two-graph solver (`solve_two_graph_hierarchical`)

Accepted outputs are written as:
- <prefix>.json (level dict with layer1/layer2)
- <prefix>_map.txt (ASCII preview)
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from graph_solver_scratch import (
    CHIP_IDS,
    EXIT_IDS,
    KEY_TO_INDEX,
    LOCK_TO_INDEX,
    SOCKET_IDS,
    START_IDS,
    effective_tile_id,
    solve_with_chip_state,
)
from room_macro_micro_bfs_solver import solve_two_graph_hierarchical, validate_all_solution_paths
from level_renderer import render_level
from path_gif_renderer import render_route_gif
from path_icon_renderer import create_path_icon_sheet

WIDTH = 32
HEIGHT = 32
TOTAL = WIDTH * HEIGHT

FLOOR = 0x00
WALL = 0x01

BLUE_KEY = 0x64
RED_KEY = 0x65
GREEN_KEY = 0x66
YELLOW_KEY = 0x67

BLUE_LOCK = 0x16
RED_LOCK = 0x17
GREEN_LOCK = 0x18
YELLOW_LOCK = 0x19

START = 0x6C
EXIT = 0x15
CHIP = 0x02
SOCKET = 0x21
WATER = 0x03
ICE = 0x0C
FIRE = 0x04
FORCE_FLOOR = 0x0D
FLIPPERS = 0x68
FIRE_BOOTS = 0x69
ICE_SKATES = 0x6A
SUCTION_BOOTS = 0x6B


def pos(x: int, y: int) -> int:
    return y * WIDTH + x


def carve_rect(layer1: list[int], x0: int, y0: int, x1: int, y1: int) -> None:
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            layer1[pos(x, y)] = FLOOR


def carve_h(layer1: list[int], y: int, x0: int, x1: int) -> None:
    lo, hi = sorted((x0, x1))
    for x in range(lo, hi + 1):
        layer1[pos(x, y)] = FLOOR


def carve_v(layer1: list[int], x: int, y0: int, y1: int) -> None:
    lo, hi = sorted((y0, y1))
    for y in range(lo, hi + 1):
        layer1[pos(x, y)] = FLOOR


def place(layer1: list[int], layer2: list[int], x: int, y: int, tile: int) -> None:
    layer1[pos(x, y)] = FLOOR
    layer2[pos(x, y)] = tile


def draw_room_shell(layer1: list[int], box: tuple[int, int, int, int], border_tile: int) -> None:
    x0, y0, x1, y1 = box
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if x in (x0, x1) or y in (y0, y1):
                layer1[pos(x, y)] = border_tile
            else:
                layer1[pos(x, y)] = FLOOR


def draw_room_shell_with_openings(
    layer1: list[int],
    box: tuple[int, int, int, int],
    border_tile: int,
    open_cells: set[tuple[int, int]],
) -> None:
    x0, y0, x1, y1 = box
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if x in (x0, x1) or y in (y0, y1):
                layer1[pos(x, y)] = FLOOR if (x, y) in open_cells else border_tile
            else:
                layer1[pos(x, y)] = FLOOR


def opening_cell(box: tuple[int, int, int, int], other: tuple[int, int, int, int]) -> tuple[int, int]:
    x0, y0, x1, y1 = box
    ox0, oy0, ox1, oy1 = other
    if ox0 > x0:
        return x1, y0 + 1
    if ox0 < x0:
        return x0, y0 + 1
    if oy0 > y0:
        return x0 + 1, y1
    return x0 + 1, y0


def connector_tile(prev_box: tuple[int, int, int, int], next_box: tuple[int, int, int, int]) -> tuple[int, int]:
    if prev_box[1] == next_box[1]:
        if next_box[0] > prev_box[0]:
            return prev_box[2] + 1, prev_box[1] + 1
        return next_box[2] + 1, prev_box[1] + 1
    if next_box[1] > prev_box[1]:
        return prev_box[0] + 1, prev_box[3] + 1
    return prev_box[0] + 1, next_box[3] + 1


def room_box_for_index(index: int, room_size: int = 4, step: int = 5, columns: int = 5) -> tuple[int, int, int, int]:
    row = index // columns
    col_in_row = index % columns
    if row % 2 == 0:
        col = col_in_row
    else:
        col = columns - 1 - col_in_row
    x0 = 2 + col * step
    y0 = 2 + row * step
    return x0, y0, x0 + room_size - 1, y0 + room_size - 1


def build_candidate(rng: random.Random, level_number: int = 9001) -> dict:
    """Construct a room-based dungeon with random key and boot counts.

    Each sampled key or boot gets its own room and immediate gate to the next room.
    The total number of rooms grows with the sampled progression sequence.
    """
    layer1 = [WALL] * TOTAL
    layer2 = [0x00] * TOTAL

    key_specs = [
        ("blue", BLUE_KEY, BLUE_LOCK),
        ("red", RED_KEY, RED_LOCK),
        ("green", GREEN_KEY, GREEN_LOCK),
        ("yellow", YELLOW_KEY, YELLOW_LOCK),
    ]
    boot_specs = [
        ("flippers", FLIPPERS, WATER, "water"),
        ("fire_boots", FIRE_BOOTS, FIRE, "fire"),
        ("ice_skates", ICE_SKATES, ICE, "ice"),
        ("suction_boots", SUCTION_BOOTS, FORCE_FLOOR, "force_floor"),
    ]

    while True:
        counts: list[tuple[str, int, int, int, int]] = []
        total_items = 0
        total_keys = 0
        total_boots = 0
        for name, key_tile, lock_tile in key_specs:
            count = rng.randint(0, 2)
            counts.append((name, key_tile, lock_tile, count, 0))
            total_items += count
            total_keys += count
        for name, boot_tile, hazard_tile, hazard_name in boot_specs:
            count = rng.randint(0, 2)
            counts.append((name, boot_tile, hazard_tile, count, 1))
            total_items += count
            total_boots += count
        if total_items == 0 or total_keys == 0 or total_boots == 0:
            continue
        if total_items > 12:
            continue
        break

    progression: list[dict] = []
    for name, tile, gate_tile, count, kind in counts:
        for _ in range(count):
            progression.append({"name": name, "tile": tile, "gate": gate_tile, "kind": kind})

    rng.shuffle(progression)

    room_count = len(progression) + 3
    room_boxes = [room_box_for_index(i) for i in range(room_count)]
    # Start room.
    start_box = room_boxes[0]
    sx0, sy0, sx1, sy1 = start_box
    start_openings = {opening_cell(start_box, room_boxes[1])}
    draw_room_shell_with_openings(layer1, start_box, WALL, start_openings)
    sx, sy = sx0 + 1, sy0 + 1
    place(layer1, layer2, sx, sy, START)
    first_box = room_boxes[1]
    open_x, open_y = connector_tile(start_box, first_box)
    layer1[pos(open_x, open_y)] = FLOOR

    # Item rooms with a gate immediately after each one.
    chips_required = 0
    chip_positions: list[tuple[int, int]] = []
    for idx, item in enumerate(progression, start=1):
        room_box = room_boxes[idx]
        room_border = WALL if item["kind"] == 0 else item["gate"]
        room_openings = {opening_cell(room_box, room_boxes[idx - 1]), opening_cell(room_box, room_boxes[idx + 1])}
        draw_room_shell_with_openings(layer1, room_box, room_border, room_openings)
        x0, y0, x1, y1 = room_box
        item_x, item_y = x0 + 1, y0 + 1
        place(layer1, layer2, item_x, item_y, item["tile"])
        chip_x, chip_y = x1 - 1, y1 - 1
        if layer2[pos(chip_x, chip_y)] == 0:
            place(layer1, layer2, chip_x, chip_y, CHIP)
            chip_positions.append((chip_x, chip_y))

        prev_box = room_boxes[idx - 1]
        next_box = room_boxes[idx + 1]
        gate_x, gate_y = connector_tile(room_box, next_box)
        if item["kind"] == 0:
            place(layer1, layer2, gate_x, gate_y, item["gate"])
        else:
            layer1[pos(gate_x, gate_y)] = item["gate"]

    # Socket room and exit room.
    socket_room = room_boxes[-2]
    exit_room = room_boxes[-1]
    draw_room_shell_with_openings(layer1, socket_room, WALL, {opening_cell(socket_room, room_boxes[-3]), opening_cell(socket_room, exit_room)})
    draw_room_shell_with_openings(layer1, exit_room, WALL, {opening_cell(exit_room, socket_room)})
    ex, ey = exit_room[0] + 1, exit_room[1] + 1
    place(layer1, layer2, ex, ey, EXIT)

    # Connect the final item room to the socket room, then socket to exit.
    if progression:
        last_item_box = room_boxes[len(progression)]
        gate_x, gate_y = connector_tile(last_item_box, socket_room)
        layer1[pos(gate_x, gate_y)] = FLOOR
    gate_x, gate_y = connector_tile(socket_room, exit_room)
    place(layer1, layer2, gate_x, gate_y, SOCKET)

    # Randomize chip coverage across the remaining rooms.
    for i, box in enumerate(room_boxes[1:-2], start=1):
        x0, y0, x1, y1 = box
        if i % 2 == 0:
            cx, cy = x0 + 2, y0 + 2
        else:
            cx, cy = x1 - 1, y1 - 1
        if layer2[pos(cx, cy)] == 0:
            place(layer1, layer2, cx, cy, CHIP)
            chip_positions.append((cx, cy))

    # Ensure at least one chip if rooms were too sparse.
    if not chip_positions:
        place(layer1, layer2, room_boxes[1][0] + 1, room_boxes[1][1] + 1, CHIP)
        chip_positions.append((room_boxes[1][0] + 1, room_boxes[1][1] + 1))

    chips_required = len(chip_positions)

    return {
        "size": 0,
        "number": level_number,
        "time": 999,
        "chips": chips_required,
        "template_name": f"snake/{len(progression)}-items",
        "layer1": layer1,
        "layer2": layer2,
    }


def render_ascii(level: dict) -> str:
    key_glyph = {BLUE_KEY: "b", RED_KEY: "r", GREEN_KEY: "g", YELLOW_KEY: "y"}
    lock_glyph = {BLUE_LOCK: "B", RED_LOCK: "R", GREEN_LOCK: "G", YELLOW_LOCK: "Y"}

    lines: list[str] = []
    for y in range(HEIGHT):
        row: list[str] = []
        for x in range(WIDTH):
            t = effective_tile_id(level, pos(x, y))
            if t == WALL:
                row.append("#")
            elif t in START_IDS:
                row.append("S")
            elif t in EXIT_IDS:
                row.append("E")
            elif t in CHIP_IDS:
                row.append("C")
            elif t in SOCKET_IDS:
                row.append("O")
            elif t in key_glyph:
                row.append(key_glyph[t])
            elif t in lock_glyph:
                row.append(lock_glyph[t])
            elif t == WATER:
                row.append("~")
            elif t == ICE:
                row.append("*")
            elif t == FLIPPERS:
                row.append("f")
            elif t == ICE_SKATES:
                row.append("i")
            elif t in KEY_TO_INDEX:
                row.append("k")
            elif t in LOCK_TO_INDEX:
                row.append("L")
            else:
                row.append(".")
        lines.append("".join(row))
    return "\n".join(lines)


def validate(level: dict) -> tuple[bool, dict, dict, dict]:
    tile = solve_with_chip_state(level)
    two = solve_two_graph_hierarchical(level, collect_all=True)
    universal = validate_all_solution_paths(level)
    ok = bool(tile.get("solvable")) and bool(two.get("solvable")) and bool(universal.get("valid"))
    return ok, tile, two, universal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and solver-verify a Key-Pyramid-like dungeon.")
    parser.add_argument("--seed", type=int, default=7, help="Base RNG seed.")
    parser.add_argument("--max-attempts", type=int, default=100, help="Max generation attempts.")
    parser.add_argument(
        "--output-prefix",
        type=str,
        default="generated_key_pyramid_like",
        help="Output file prefix for JSON and ASCII map.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    accepted_level = None
    accepted_tile = None
    accepted_two = None
    accepted_universal = None
    accepted_seed = None

    for i in range(args.max_attempts):
        seed_i = args.seed + i
        rng = random.Random(seed_i)
        candidate = build_candidate(rng, level_number=9001 + i)
        ok, tile_res, two_res, universal_res = validate(candidate)
        if ok:
            accepted_level = candidate
            accepted_tile = tile_res
            accepted_two = two_res
            accepted_universal = universal_res
            accepted_seed = seed_i
            break

    if accepted_level is None:
        print("Failed to generate a solver-verified level.")
        print(f"Tried attempts: {args.max_attempts}")
        return

    out_json = Path(f"{args.output_prefix}.json")
    out_map = Path(f"{args.output_prefix}_map.txt")
    out_png = Path(f"{args.output_prefix}.png")
    out_gif = Path(f"{args.output_prefix}_two_graph_route.gif")
    out_sheet = Path(f"{args.output_prefix}_two_graph_path_icons.png")

    out_json.write_text(json.dumps(accepted_level, indent=2))
    out_map.write_text(render_ascii(accepted_level) + "\n")

    img = render_level(accepted_level, tile_size=24)
    img.save(out_png)

    img_path = out_png
    render_route_gif(
        level_image_path=img_path,
        positions=accepted_two["positions"],
        out_path=out_gif,
        tile_size=24,
        frame_ms=120,
        level_data=accepted_level,
    )
    create_path_icon_sheet(
        level_image_path=img_path,
        positions=accepted_two["positions"],
        out_path=out_sheet,
        tile_size=24,
        columns=16,
        title=f'Generated dungeon ({accepted_level.get("template_name", "random")})',
    )

    print("Generated solver-verified dungeon.")
    print("Seed:", accepted_seed)
    print("Template:", accepted_level.get("template_name"))
    print("JSON:", out_json)
    print("ASCII map:", out_map)
    print("PNG:", out_png)
    print("GIF:", out_gif)
    print("Path icons:", out_sheet)
    print("Chips required:", accepted_level["chips"])
    print("Tile solver -> moves:", accepted_tile.get("moves"), "visited:", accepted_tile.get("visited_states"))
    print(
        "Two-graph solver -> moves:",
        accepted_two.get("moves"),
        "macro visited:",
        accepted_two.get("macro_visited_states"),
        "micro visited:",
        accepted_two.get("micro_visited_states"),
    )
    print(
        "Universal solution check ->",
        "valid" if accepted_universal and accepted_universal.get("valid") else "invalid",
        "expanded:",
        accepted_universal.get("expanded_states") if accepted_universal else None,
    )


if __name__ == "__main__":
    main()
