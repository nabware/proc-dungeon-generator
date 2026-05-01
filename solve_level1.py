#!/usr/bin/env python3
"""Fast, standalone BFS solver for Chip's Challenge level 1.

This script parses only level 1 from CHIPS.DAT and runs BFS with chip
collection and socket constraints, then prints the shortest path.
"""

from __future__ import annotations

import struct
import time
from collections import deque
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None
else:
    try:
        from level_renderer import render_dat_level
    except Exception:
        render_dat_level = None

WIDTH = 32
HEIGHT = 32
TOTAL_TILES = WIDTH * HEIGHT

# Core tile IDs used by solver.
START_IDS = {0x6C, 0x6D, 0x6E, 0x6F}
EXIT_IDS = {0x15}
CHIP_IDS = {0x02, 0x20}
SOCKET_IDS = {0x21, 0x22}
KEY_TO_INDEX = {0x64: 0, 0x65: 1, 0x66: 2, 0x67: 3}  # blue, red, green, yellow
LOCK_TO_INDEX = {0x16: 0, 0x17: 1, 0x18: 2, 0x19: 3}

BLOCKED_IDS = {
    0x01, 0x10,  # Wall
    0x05,        # Invisible Wall
    0x0A,        # Dirt Block
    0x1F,        # Real Blue Wall
    0x25,        # Toggle Wall (Closed)
    0x2B,        # Trap
    0x2C,        # Hidden Wall
    0x2E,        # Recessed Wall
}

HAZARD_IDS = {
    0x03, 0x30,  # Water variants
    0x04,        # Fire
    0x29, 0x2A, 0x38,  # Bomb variants
    # Monsters
    0x40, 0x41, 0x42, 0x43,
    0x44, 0x45, 0x46, 0x47,
    0x48, 0x49, 0x4A, 0x4B,
    0x4C, 0x4D, 0x4E, 0x4F,
    0x50, 0x51, 0x52, 0x53,
    0x54, 0x55, 0x56, 0x57,
    0x58, 0x59, 0x5A, 0x5B,
    0x5C, 0x5D, 0x5E, 0x5F,
    0x60, 0x61, 0x62, 0x63,
}


def decode_layer(blob: bytes) -> list[int]:
    tiles: list[int] = []
    i = 0
    while len(tiles) < TOTAL_TILES:
        if blob[i] == 0xFF:
            count = blob[i + 1]
            tile_id = blob[i + 2]
            tiles.extend([tile_id] * count)
            i += 3
        else:
            tiles.append(blob[i])
            i += 1
    return tiles[:TOTAL_TILES]


def parse_level_1(dat_bytes: bytes) -> dict:
    # DAT file starts with magic (4 bytes), num levels (2 bytes), then level 1.
    offset = 6
    level_size = struct.unpack_from("<H", dat_bytes, offset)[0]
    number = struct.unpack_from("<H", dat_bytes, offset + 2)[0]
    time_limit = struct.unpack_from("<H", dat_bytes, offset + 4)[0]
    chips_required = struct.unpack_from("<H", dat_bytes, offset + 6)[0]

    layer1_size = struct.unpack_from("<H", dat_bytes, offset + 10)[0]
    layer1_data = dat_bytes[offset + 12 : offset + 12 + layer1_size]
    layer1 = decode_layer(layer1_data)

    next_offset = offset + 12 + layer1_size
    layer2_size = struct.unpack_from("<H", dat_bytes, next_offset)[0]
    layer2_data = dat_bytes[next_offset + 2 : next_offset + 2 + layer2_size]
    layer2 = decode_layer(layer2_data)

    return {
        "size": level_size,
        "number": number,
        "time": time_limit,
        "chips": chips_required,
        "layer1": layer1,
        "layer2": layer2,
    }


def effective_tile(level: dict, pos: int) -> int:
    top = level["layer2"][pos]
    return top if top != 0x00 else level["layer1"][pos]


def find_start(level: dict) -> int | None:
    for i, t in enumerate(level["layer2"]):
        if t in START_IDS:
            return i
    for i, t in enumerate(level["layer1"]):
        if t in START_IDS:
            return i
    return None


def solve_level_1_bfs(level: dict) -> dict:
    start = find_start(level)
    if start is None:
        return {"solvable": False, "reason": "No Chip start tile found."}

    chip_positions = []
    for pos in range(TOTAL_TILES):
        if level["layer1"][pos] in CHIP_IDS or level["layer2"][pos] in CHIP_IDS:
            chip_positions.append(pos)

    chip_index = {pos: idx for idx, pos in enumerate(chip_positions)}
    chips_required = int(level["chips"])

    # Each lock tile gets a unique bit so unlocking one specific door persists.
    lock_positions = [
        pos for pos in range(TOTAL_TILES)
        if effective_tile(level, pos) in LOCK_TO_INDEX
    ]
    lock_pos_to_bit = {pos: idx for idx, pos in enumerate(lock_positions)}

    start_mask = 0
    if start in chip_index:
        start_mask |= 1 << chip_index[start]

    start_keys = (0, 0, 0, 0)  # blue, red, green, yellow
    start_opened_locks = 0
    start_state = (start, start_mask, start_keys, start_opened_locks)
    q = deque([start_state])
    seen = {start_state}
    parent = {start_state: None}
    move_taken = {start_state: None}

    dirs = [(-1, 0, "L"), (1, 0, "R"), (0, -1, "U"), (0, 1, "D")]

    def is_passable(pos: int, mask: int, keys: tuple[int, int, int, int], opened_locks: int) -> bool:
        tile = effective_tile(level, pos)

        # Locked doors become passable after we open that exact door tile once.
        if tile in LOCK_TO_INDEX:
            bit = lock_pos_to_bit[pos]
            if opened_locks & (1 << bit):
                return True

            color = LOCK_TO_INDEX[tile]
            return keys[color] > 0

        if tile in BLOCKED_IDS or tile in HAZARD_IDS:
            return False
        if tile in SOCKET_IDS and mask.bit_count() < chips_required:
            return False
        return True

    def is_goal(pos: int, mask: int) -> bool:
        if mask.bit_count() < chips_required:
            return False
        return effective_tile(level, pos) in EXIT_IDS

    goal_state = None
    while q:
        pos, mask, keys, opened_locks = q.popleft()
        if is_goal(pos, mask):
            goal_state = (pos, mask, keys, opened_locks)
            break

        x = pos % WIDTH
        y = pos // WIDTH

        for dx, dy, step in dirs:
            nx = x + dx
            ny = y + dy
            if nx < 0 or nx >= WIDTH or ny < 0 or ny >= HEIGHT:
                continue

            npos = ny * WIDTH + nx
            if not is_passable(npos, mask, keys, opened_locks):
                continue

            nmask = mask
            if npos in chip_index:
                nmask |= 1 << chip_index[npos]

            nkeys = list(keys)
            nopened_locks = opened_locks

            ntile = effective_tile(level, npos)
            if ntile in KEY_TO_INDEX:
                nkeys[KEY_TO_INDEX[ntile]] += 1

            if ntile in LOCK_TO_INDEX:
                bit = lock_pos_to_bit[npos]
                if not (nopened_locks & (1 << bit)):
                    color = LOCK_TO_INDEX[ntile]
                    nkeys[color] -= 1
                    nopened_locks |= (1 << bit)

            state = (npos, nmask, tuple(nkeys), nopened_locks)
            if state in seen:
                continue

            seen.add(state)
            parent[state] = (pos, mask, keys, opened_locks)
            move_taken[state] = step
            q.append(state)

    if goal_state is None:
        return {
            "solvable": False,
            "reason": "No path found to exit after collecting required chips.",
            "chips_required": chips_required,
            "chips_in_map": len(chip_positions),
        }

    path = []
    positions = []
    cur = goal_state
    positions.append(cur[0])
    while parent[cur] is not None:
        path.append(move_taken[cur])
        cur = parent[cur]
        positions.append(cur[0])
    path.reverse()
    positions.reverse()

    return {
        "solvable": True,
        "moves": len(path),
        "path": "".join(path),
        "positions": positions,
        "start_pos": start,
        "chips_required": chips_required,
        "chips_in_map": len(chip_positions),
    }


def pos_to_xy(pos: int) -> tuple[int, int]:
    return (pos % WIDTH, pos // WIDTH)


def create_path_icon_sheet(
    level_image_path: Path,
    positions: list[int],
    out_path: Path,
    tile_size: int = 32,
    columns: int = 16,
) -> None:
    """Create an image sheet of tile icons along the solved path.

    The function crops each visited tile from the rendered level image and lays
    them out left-to-right, top-to-bottom with step numbers.
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is not available. Install pillow to export images.")

    level_img = Image.open(level_image_path).convert("RGB")

    step_count = len(positions)
    rows = (step_count + columns - 1) // columns
    header_h = 28
    sheet_w = columns * tile_size
    sheet_h = rows * tile_size + header_h
    sheet = Image.new("RGB", (sheet_w, sheet_h), (20, 20, 24))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), "Level 1 BFS Path Tiles (step order)", fill=(230, 230, 240))

    for idx, pos in enumerate(positions):
        gx, gy = pos_to_xy(pos)
        src_box = (
            gx * tile_size,
            gy * tile_size,
            (gx + 1) * tile_size,
            (gy + 1) * tile_size,
        )
        icon = level_img.crop(src_box)

        col = idx % columns
        row = idx // columns
        dx = col * tile_size
        dy = header_h + row * tile_size
        sheet.paste(icon, (dx, dy))

        # Step index marker in top-left corner of each icon.
        draw.rectangle((dx, dy, dx + 13, dy + 10), fill=(0, 0, 0))
        draw.text((dx + 1, dy), str(idx), fill=(255, 255, 255))

    sheet.save(out_path)


def main() -> None:
    dat_path = Path("/home/nabeel/proc-dungeon-generator/CCUP/Apps/Chip's Challenge/CHIPS.DAT")
    data = dat_path.read_bytes()

    t0 = time.perf_counter()
    level = parse_level_1(data)
    result = solve_level_1_bfs(level)
    elapsed = time.perf_counter() - t0

    print(f"Level: {level['number']}")
    print(f"Time limit: {level['time']} seconds")
    print(f"BFS runtime: {elapsed:.4f}s")
    print(f"Solvable: {result['solvable']}")
    print(f"Chips required: {result.get('chips_required')}")
    print(f"Chips detected: {result.get('chips_in_map')}")

    if result["solvable"]:
        print(f"Shortest move count: {result['moves']}")
        print(f"Path (L/R/U/D): {result['path']}")

        level_img_path = Path("/home/nabeel/proc-dungeon-generator/level1.png")
        out_sheet = Path("/home/nabeel/proc-dungeon-generator/level1_path_icons.png")
        if not level_img_path.exists() and render_dat_level is not None:
            try:
                print("level1.png not found — rendering from DAT...")
                render_dat_level(dat_path, 1, level_img_path, tile_size=32)
                print(f"Rendered {level_img_path}")
            except Exception as e:
                print("Failed to render level1.png:", e)

        if level_img_path.exists():
            create_path_icon_sheet(level_img_path, result["positions"], out_sheet)
            print(f"Path icon sheet: {out_sheet}")
        else:
            print("Path icon sheet skipped: level1.png not found.")
            print("Run level_renderer.py 1 first to generate the full level image.")
    else:
        print(f"Reason: {result.get('reason')}")


if __name__ == "__main__":
    main()
