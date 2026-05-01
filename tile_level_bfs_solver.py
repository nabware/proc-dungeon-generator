#!/usr/bin/env python3
"""Scratch solver file: BFS with chip-state and socket gating."""

import argparse
from collections import deque
from pathlib import Path
import struct
import time

START_IDS = {0x6C, 0x6D, 0x6E, 0x6F}
EXIT_IDS = {0x15}
CHIP_IDS = {0x02, 0x20}
SOCKET_IDS = {0x21, 0x22}
KEY_TO_INDEX = {0x64: 0, 0x65: 1, 0x66: 2, 0x67: 3}
LOCK_TO_INDEX = {0x16: 0, 0x17: 1, 0x18: 2, 0x19: 3}

FLIPPERS_ID = 0x68
FIRE_BOOTS_ID = 0x69
ICE_SKATES_ID = 0x6A
SUCTION_BOOTS_ID = 0x6B
WATER_IDS = {0x03, 0x30}
FIRE_IDS = {0x04}
ICE_IDS = {0x0C, 0x1A, 0x1B, 0x1C, 0x1D}
FORCE_FLOOR_IDS = {0x12, 0x13, 0x0D, 0x14}

# For this scratch mode, only dark-gray wall tiles are hard-blocked.
BLOCKED_IDS = {
    0x01, 0x10,  # Wall
}


def effective_tile_id(level: dict, pos: int) -> int:
    """Return the effective tile ID at pos (top layer wins if not floor)."""
    top = level["layer2"][pos]
    return top if top != 0x00 else level["layer1"][pos]


def find_start_position(level: dict) -> int | None:
    """Return start tile index for a parsed level, or None if missing."""
    for i, tile in enumerate(level["layer2"]):
        if tile in START_IDS:
            return i
    for i, tile in enumerate(level["layer1"]):
        if tile in START_IDS:
            return i
    return None


def pos_to_xy(pos: int, width: int = 32) -> tuple[int, int]:
    return (pos % width, pos // width)


def decode_layer(blob: bytes, total_tiles: int = 32 * 32) -> list[int]:
    """Decode one RLE DAT layer into tile IDs."""
    tiles: list[int] = []
    i = 0
    while len(tiles) < total_tiles:
        if blob[i] == 0xFF:
            count = blob[i + 1]
            tile_id = blob[i + 2]
            tiles.extend([tile_id] * count)
            i += 3
        else:
            tiles.append(blob[i])
            i += 1
    return tiles[:total_tiles]


def load_level_by_number(dat_path: Path, target_number: int) -> dict:
    """Load one level by DAT level number from CHIPS.DAT."""
    data = dat_path.read_bytes()
    num_levels = struct.unpack_from("<H", data, 4)[0]
    offset = 6  # magic (4) + num-levels (2)

    for _ in range(num_levels):
        level_size = struct.unpack_from("<H", data, offset)[0]
        number = struct.unpack_from("<H", data, offset + 2)[0]
        time_limit = struct.unpack_from("<H", data, offset + 4)[0]
        chips_required = struct.unpack_from("<H", data, offset + 6)[0]

        layer1_size = struct.unpack_from("<H", data, offset + 10)[0]
        layer1_data = data[offset + 12 : offset + 12 + layer1_size]
        layer1 = decode_layer(layer1_data)

        next_offset = offset + 12 + layer1_size
        layer2_size = struct.unpack_from("<H", data, next_offset)[0]
        layer2_data = data[next_offset + 2 : next_offset + 2 + layer2_size]
        layer2 = decode_layer(layer2_data)

        if number == target_number:
            return {
                "size": level_size,
                "number": number,
                "time": time_limit,
                "chips": chips_required,
                "layer1": layer1,
                "layer2": layer2,
            }

        offset += level_size + 2

    raise ValueError(f"Level number {target_number} not found in DAT.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solve a Chip's Challenge DAT level with BFS scratch solver.")
    parser.add_argument("--level", type=int, default=3, help="DAT level number to solve (default: 3).")
    parser.add_argument(
        "--dat",
        type=Path,
        default=Path("/home/nabeel/chips-challenge-2/CCUP/Apps/Chip's Challenge/CHIPS.DAT"),
        help="Path to CHIPS.DAT.",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=None,
        help="Output prefix for GIF and PNG files (default: level{N}).",
    )
    parser.add_argument(
        "--level-image",
        type=Path,
        default=None,
        help="Optional explicit level image path to use for path sheet/GIF background.",
    )
    return parser.parse_args()


def resolve_level_image_path(
    target_level: int,
    dat_path: Path,
    output_prefix: str,
    explicit_level_image: Path | None = None,
) -> Path:
    """Resolve the background image path for route rendering.

    Priority:
    1) explicit --level-image
    2) {output_prefix}_level.png
    3) {output_prefix}.png
    4) level{N}.png
    """
    candidates: list[Path] = []
    if explicit_level_image is not None:
        candidates.append(explicit_level_image)
    candidates.append(Path(f"{output_prefix}_level.png"))
    candidates.append(Path(f"{output_prefix}.png"))
    candidates.append(Path(f"level{target_level}.png"))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Return the final fallback path so caller can emit a useful not-found message.
    return candidates[-1]


def solve_with_chip_state(level: dict, width: int = 32, height: int = 32) -> dict:
    start = find_start_position(level)
    if start is None:
        return {"solvable": False, "reason": "No start tile found."}

    total_tiles = width * height
    chips_required = int(level["chips"])

    tiles = [effective_tile_id(level, pos) for pos in range(total_tiles)]

    chip_positions = [pos for pos in range(total_tiles) if tiles[pos] in CHIP_IDS]
    chip_index = {pos: i for i, pos in enumerate(chip_positions)}
    key_positions = [pos for pos in range(total_tiles) if tiles[pos] in KEY_TO_INDEX]
    key_index = {pos: i for i, pos in enumerate(key_positions)}
    lock_positions = [pos for pos in range(total_tiles) if tiles[pos] in LOCK_TO_INDEX]
    lock_pos_to_bit = {pos: i for i, pos in enumerate(lock_positions)}

    start_mask = 0
    if start in chip_index:
        start_mask |= 1 << chip_index[start]

    start_key_mask = 0
    start_keys = [0, 0, 0, 0]
    start_has_flippers = False
    start_has_fire_boots = False
    start_has_ice_skates = False
    start_has_suction_boots = False
    if start in key_index:
        start_key_mask |= 1 << key_index[start]
        start_keys[KEY_TO_INDEX[tiles[start]]] += 1
    if tiles[start] == FLIPPERS_ID:
        start_has_flippers = True
    if tiles[start] == FIRE_BOOTS_ID:
        start_has_fire_boots = True
    if tiles[start] == ICE_SKATES_ID:
        start_has_ice_skates = True
    if tiles[start] == SUCTION_BOOTS_ID:
        start_has_suction_boots = True

    start_opened_locks = 0
    start_state = (
        start,
        start_mask,
        tuple(start_keys),
        start_key_mask,
        start_opened_locks,
        start_has_flippers,
        start_has_fire_boots,
        start_has_ice_skates,
        start_has_suction_boots,
    )
    q = deque([start_state])
    seen = {start_state}
    parent = {start_state: None}
    move_taken = {start_state: None}

    dirs = [(-1, 0, "L"), (1, 0, "R"), (0, -1, "U"), (0, 1, "D")]

    def is_passable(
        pos: int,
        chip_mask: int,
        keys: tuple[int, int, int, int],
        opened_locks: int,
        has_flippers: bool,
        has_fire_boots: bool,
        has_ice_skates: bool,
        has_suction_boots: bool,
    ) -> bool:
        tile = tiles[pos]
        if tile in BLOCKED_IDS:
            return False
        if tile in WATER_IDS and not has_flippers:
            return False
        if tile in FIRE_IDS and not has_fire_boots:
            return False
        if tile in ICE_IDS and not has_ice_skates:
            return False
        if tile in FORCE_FLOOR_IDS and not has_suction_boots:
            return False
        if tile in LOCK_TO_INDEX:
            bit = lock_pos_to_bit[pos]
            if opened_locks & (1 << bit):
                return True

            color = LOCK_TO_INDEX[tile]
            return keys[color] > 0
        if tile in SOCKET_IDS and chip_mask.bit_count() < chips_required:
            return False
        return True

    def is_goal(pos: int, chip_mask: int) -> bool:
        return tiles[pos] in EXIT_IDS and chip_mask.bit_count() >= chips_required

    goal_state = None
    while q:
        (
            pos,
            chip_mask,
            keys,
            key_mask,
            opened_locks,
            has_flippers,
            has_fire_boots,
            has_ice_skates,
            has_suction_boots,
        ) = q.popleft()
        if is_goal(pos, chip_mask):
            goal_state = (
                pos,
                chip_mask,
                keys,
                key_mask,
                opened_locks,
                has_flippers,
                has_fire_boots,
                has_ice_skates,
                has_suction_boots,
            )
            break

        x, y = pos_to_xy(pos, width)
        for dx, dy, step in dirs:
            nx = x + dx
            ny = y + dy
            if nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue

            npos = ny * width + nx
            if not is_passable(
                npos,
                chip_mask,
                keys,
                opened_locks,
                has_flippers,
                has_fire_boots,
                has_ice_skates,
                has_suction_boots,
            ):
                continue

            nmask = chip_mask
            if npos in chip_index:
                nmask |= 1 << chip_index[npos]

            nkeys = list(keys)
            nkey_mask = key_mask
            nopened_locks = opened_locks
            nhas_flippers = has_flippers
            nhas_fire_boots = has_fire_boots
            nhas_ice_skates = has_ice_skates
            nhas_suction_boots = has_suction_boots

            ntile = tiles[npos]
            if ntile in KEY_TO_INDEX:
                bit = 1 << key_index[npos]
                if not (nkey_mask & bit):
                    nkeys[KEY_TO_INDEX[ntile]] += 1
                    nkey_mask |= bit
            if ntile == FLIPPERS_ID:
                nhas_flippers = True
            if ntile == FIRE_BOOTS_ID:
                nhas_fire_boots = True
            if ntile == ICE_SKATES_ID:
                nhas_ice_skates = True
            if ntile == SUCTION_BOOTS_ID:
                nhas_suction_boots = True

            if ntile in LOCK_TO_INDEX:
                bit = lock_pos_to_bit[npos]
                if not (nopened_locks & (1 << bit)):
                    color = LOCK_TO_INDEX[ntile]
                    # Green key is reusable in Chip's Challenge.
                    if color != 2:
                        nkeys[color] -= 1
                    nopened_locks |= (1 << bit)

            state = (
                npos,
                nmask,
                tuple(nkeys),
                nkey_mask,
                nopened_locks,
                nhas_flippers,
                nhas_fire_boots,
                nhas_ice_skates,
                nhas_suction_boots,
            )
            if state in seen:
                continue

            seen.add(state)
            parent[state] = (
                pos,
                chip_mask,
                keys,
                key_mask,
                opened_locks,
                has_flippers,
                has_fire_boots,
                has_ice_skates,
                has_suction_boots,
            )
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
        "chips_required": chips_required,
        "chips_in_map": len(chip_positions),
    }


def main() -> None:
    args = parse_args()
    dat_path = args.dat
    target_level = args.level
    output_prefix = args.output_prefix or f"level{target_level}"
    explicit_level_image = args.level_image

    level_data = load_level_by_number(dat_path, target_level)
    start = find_start_position(level_data)
    t0 = time.perf_counter()
    result = solve_with_chip_state(level_data)
    elapsed = time.perf_counter() - t0

    print(f"Level {target_level} start index:", start)
    if start is not None:
        print(f"Level {target_level} start (x, y):", pos_to_xy(start))
    print("Solvable:", result["solvable"])
    print("Chips required:", result.get("chips_required"))
    print("Chips detected:", result.get("chips_in_map"))
    print("Solve time (s):", f"{elapsed:.6f}")
    if result["solvable"]:
        print("Moves:", result["moves"])
        print("Path:", result["path"])

        level_img_path = resolve_level_image_path(
            target_level,
            dat_path,
            output_prefix,
            explicit_level_image,
        )
        out_sheet = Path(f"/home/nabeel/chips-challenge-2/{output_prefix}_path_icons_scratch.png")
        out_gif = Path(f"/home/nabeel/chips-challenge-2/{output_prefix}_route_scratch.gif")
        if level_img_path.exists():
            try:
                from path_gif_renderer import render_route_gif
                from path_icon_renderer import create_path_icon_sheet

                create_path_icon_sheet(level_img_path, result["positions"], out_sheet)
                print("Path icon sheet:", out_sheet)
                render_route_gif(
                    level_img_path,
                    result["positions"],
                    out_gif,
                    frame_ms=120,
                    dat_path=dat_path,
                    level_number=target_level,
                )
                print("Route GIF:", out_gif)
            except BaseException:
                print("Path renders skipped: optional image dependencies are unavailable.")
        else:
            print(f"Path icon sheet skipped: {level_img_path} not found.")
    else:
        print("Reason:", result.get("reason"))


if __name__ == "__main__":
    main()
