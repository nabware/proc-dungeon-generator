#!/usr/bin/env python3
"""Prototype: graph-based dungeon generation + solver + GIF render.

This script models a dungeon in three layers:
1) Room graph (tree of rooms)
2) Tile map expansion (walkable ground + walls + corridors)
3) State-space solver (position + keys + opened locks + collected keys)

It then renders a level PNG and a solution route GIF.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import random

from PIL import Image, ImageDraw

from path_gif_renderer import render_route_gif
from path_icon_renderer import create_path_icon_sheet

GRID_W = 32
GRID_H = 32
ROOM_SPACING = 6
OFFSET = 3

COLORS = ("R", "G", "B", "Y")
COLOR_TO_IDX = {c: i for i, c in enumerate(COLORS)}
COLOR_FILL = {
    "R": (215, 70, 70),
    "G": (70, 175, 80),
    "B": (65, 120, 210),
    "Y": (220, 195, 60),
}


@dataclass(frozen=True)
class Room:
    rid: int
    gx: int
    gy: int
    w: int
    h: int


@dataclass(frozen=True)
class Edge:
    eid: int
    parent: int
    child: int


@dataclass
class LockInfo:
    edge_id: int
    color: str
    pos: tuple[int, int]


@dataclass
class KeyInfo:
    color: str
    pos: tuple[int, int]


def xy_to_pos(x: int, y: int) -> int:
    return y * GRID_W + x


def pos_to_xy(pos: int) -> tuple[int, int]:
    return (pos % GRID_W, pos // GRID_W)


def build_room_tree(num_rooms: int, rng: random.Random) -> tuple[list[Room], list[Edge], int]:
    occupied: set[tuple[int, int]] = set()
    rooms: list[Room] = []
    edges: list[Edge] = []

    root = Room(rid=0, gx=2, gy=2, w=rng.choice((3, 5)), h=rng.choice((3, 5)))
    rooms.append(root)
    occupied.add((root.gx, root.gy))

    eid = 0
    attempts = 0
    while len(rooms) < num_rooms and attempts < num_rooms * 40:
        attempts += 1
        parent = rng.choice(rooms)
        dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        rng.shuffle(dirs)
        placed = False
        for dx, dy in dirs:
            nx, ny = parent.gx + dx, parent.gy + dy
            if not (0 <= nx <= 4 and 0 <= ny <= 4):
                continue
            if (nx, ny) in occupied:
                continue
            rid = len(rooms)
            room = Room(rid=rid, gx=nx, gy=ny, w=rng.choice((3, 5)), h=rng.choice((3, 5)))
            rooms.append(room)
            occupied.add((nx, ny))
            edges.append(Edge(eid=eid, parent=parent.rid, child=room.rid))
            eid += 1
            placed = True
            break
        if not placed:
            continue

    if len(rooms) < 3:
        raise RuntimeError("Failed to place enough rooms for a meaningful dungeon.")

    return rooms, edges, root.rid


def room_center(room: Room) -> tuple[int, int]:
    return (OFFSET + room.gx * ROOM_SPACING, OFFSET + room.gy * ROOM_SPACING)


def room_tiles(room: Room) -> list[tuple[int, int]]:
    cx, cy = room_center(room)
    x0 = max(1, cx - room.w // 2)
    x1 = min(GRID_W - 2, cx + room.w // 2)
    y0 = max(1, cy - room.h // 2)
    y1 = min(GRID_H - 2, cy + room.h // 2)
    out = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            out.append((x, y))
    return out


def carve_corridor(grid: list[list[str]], a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    ax, ay = a
    bx, by = b
    path: list[tuple[int, int]] = []

    x, y = ax, ay
    step_x = 1 if bx > ax else -1
    while x != bx:
        grid[y][x] = "."
        path.append((x, y))
        x += step_x

    step_y = 1 if by > ay else -1
    while y != by:
        grid[y][x] = "."
        path.append((x, y))
        y += step_y

    grid[y][x] = "."
    path.append((x, y))
    return path


def build_parent_map(edges: list[Edge], root_id: int) -> tuple[dict[int, int], dict[int, int], dict[int, list[int]]]:
    children: dict[int, list[int]] = {}
    for e in edges:
        children.setdefault(e.parent, []).append(e.child)

    parent: dict[int, int] = {root_id: -1}
    depth: dict[int, int] = {root_id: 0}
    q = deque([root_id])
    while q:
        r = q.popleft()
        for c in children.get(r, []):
            parent[c] = r
            depth[c] = depth[r] + 1
            q.append(c)
    return parent, depth, children


def find_room_by_id(rooms: list[Room], rid: int) -> Room:
    return next(r for r in rooms if r.rid == rid)


def place_locks_and_keys(
    rooms: list[Room],
    edges: list[Edge],
    root_id: int,
    edge_paths: dict[int, list[tuple[int, int]]],
    room_floor_tiles: dict[int, list[tuple[int, int]]],
    rng: random.Random,
) -> tuple[list[LockInfo], list[KeyInfo]]:
    parent, depth, _children = build_parent_map(edges, root_id)
    lock_candidates = [e for e in edges if depth[e.child] >= 1]
    rng.shuffle(lock_candidates)
    lock_count = max(1, len(lock_candidates) // 2)

    locks: list[LockInfo] = []
    keys: list[KeyInfo] = []

    for e in lock_candidates[:lock_count]:
        color = rng.choice(COLORS)
        path = edge_paths[e.eid]
        lock_pos = path[len(path) // 2]
        locks.append(LockInfo(edge_id=e.eid, color=color, pos=lock_pos))

        # Place key in an ancestor of the lock parent to keep progression valid.
        anc = [e.parent]
        cur = e.parent
        while cur != root_id and cur in parent:
            cur = parent[cur]
            if cur >= 0:
                anc.append(cur)
        key_room_id = rng.choice(anc)
        key_tile = rng.choice(room_floor_tiles[key_room_id])
        keys.append(KeyInfo(color=color, pos=key_tile))

    return locks, keys


def generate_dungeon(seed: int, num_rooms: int) -> dict:
    rng = random.Random(seed)

    rooms, edges, root_id = build_room_tree(num_rooms, rng)
    grid = [["#" for _ in range(GRID_W)] for _ in range(GRID_H)]

    room_floor_tiles: dict[int, list[tuple[int, int]]] = {}
    for room in rooms:
        tiles = room_tiles(room)
        room_floor_tiles[room.rid] = tiles
        for x, y in tiles:
            grid[y][x] = "."

    edge_paths: dict[int, list[tuple[int, int]]] = {}
    for e in edges:
        a = room_center(find_room_by_id(rooms, e.parent))
        b = room_center(find_room_by_id(rooms, e.child))
        edge_paths[e.eid] = carve_corridor(grid, a, b)

    parent, depth, _children = build_parent_map(edges, root_id)
    deepest_room = max(depth.items(), key=lambda kv: kv[1])[0]

    locks, keys = place_locks_and_keys(rooms, edges, root_id, edge_paths, room_floor_tiles, rng)

    start_xy = room_center(find_room_by_id(rooms, root_id))
    goal_xy = room_center(find_room_by_id(rooms, deepest_room))

    # Paint lock and key markers on top of floor.
    for li in locks:
        lx, ly = li.pos
        grid[ly][lx] = li.color.lower()
    for ki in keys:
        kx, ky = ki.pos
        if (kx, ky) != start_xy and (kx, ky) != goal_xy:
            grid[ky][kx] = li_color_upper(ki.color)

    sx, sy = start_xy
    gx, gy = goal_xy
    grid[sy][sx] = "S"
    grid[gy][gx] = "E"

    return {
        "rooms": rooms,
        "edges": edges,
        "grid": grid,
        "start": start_xy,
        "goal": goal_xy,
        "locks": locks,
        "keys": keys,
    }


def li_color_upper(color: str) -> str:
    return color.upper()


def solve_dungeon(dungeon: dict) -> dict:
    grid = dungeon["grid"]
    start_xy = dungeon["start"]
    goal_xy = dungeon["goal"]

    # Stable ordering for key collection bitmask.
    key_items = list(enumerate(dungeon["keys"]))
    key_pos_to_idx = {k.pos: idx for idx, k in key_items}
    key_idx_to_color = {idx: k.color for idx, k in key_items}

    lock_items = list(enumerate(dungeon["locks"]))
    lock_pos_to_idx = {l.pos: idx for idx, l in lock_items}
    lock_idx_to_color = {idx: l.color for idx, l in lock_items}

    def passable(x: int, y: int, keys: tuple[int, int, int, int], opened_mask: int) -> tuple[bool, tuple[int, int, int, int], int]:
        t = grid[y][x]
        new_keys = list(keys)
        new_opened = opened_mask

        if t == "#":
            return False, keys, opened_mask

        if (x, y) in lock_pos_to_idx:
            lid = lock_pos_to_idx[(x, y)]
            if not (opened_mask & (1 << lid)):
                c = lock_idx_to_color[lid]
                ci = COLOR_TO_IDX[c]
                if new_keys[ci] <= 0:
                    return False, keys, opened_mask
                new_keys[ci] -= 1
                new_opened |= (1 << lid)

        if (x, y) in key_pos_to_idx:
            kid = key_pos_to_idx[(x, y)]
            c = key_idx_to_color[kid]
            ci = COLOR_TO_IDX[c]
            # Key collection is controlled by mask in state transition.
            # Count increment is applied once when visiting uncollected key.
            pass

        return True, tuple(new_keys), new_opened

    start = xy_to_pos(*start_xy)
    goal = xy_to_pos(*goal_xy)

    init_state = (start, (0, 0, 0, 0), 0, 0)  # pos, key_counts, opened_locks, key_collected_mask
    q = deque([init_state])
    seen = {init_state}
    parent: dict[tuple, tuple | None] = {init_state: None}

    dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    goal_state = None

    while q:
        state = q.popleft()
        pos, key_counts, opened_mask, key_mask = state
        if pos == goal:
            goal_state = state
            break

        x, y = pos_to_xy(pos)
        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if nx < 0 or nx >= GRID_W or ny < 0 or ny >= GRID_H:
                continue

            ok, nkeys, nopened = passable(nx, ny, key_counts, opened_mask)
            if not ok:
                continue

            nkey_mask = key_mask
            if (nx, ny) in key_pos_to_idx:
                kid = key_pos_to_idx[(nx, ny)]
                bit = 1 << kid
                if not (nkey_mask & bit):
                    color = key_idx_to_color[kid]
                    ci = COLOR_TO_IDX[color]
                    nk = list(nkeys)
                    nk[ci] += 1
                    nkeys = tuple(nk)
                    nkey_mask |= bit

            npos = xy_to_pos(nx, ny)
            nstate = (npos, nkeys, nopened, nkey_mask)
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            q.append(nstate)

    if goal_state is None:
        return {"solvable": False, "reason": "No path to goal with key-lock constraints."}

    positions: list[int] = []
    cur = goal_state
    while cur is not None:
        positions.append(cur[0])
        cur = parent[cur]
    positions.reverse()

    return {
        "solvable": True,
        "positions": positions,
        "moves": len(positions) - 1,
        "states_explored": len(seen),
    }


def render_level_png(dungeon: dict, out_png: Path, tile_size: int = 32) -> None:
    grid = dungeon["grid"]
    img = Image.new("RGB", (GRID_W * tile_size, GRID_H * tile_size), (25, 27, 30))
    draw = ImageDraw.Draw(img)

    for y in range(GRID_H):
        for x in range(GRID_W):
            t = grid[y][x]
            left = x * tile_size
            top = y * tile_size
            right = left + tile_size - 1
            bottom = top + tile_size - 1

            if t == "#":
                fill = (20, 22, 26)
            else:
                fill = (58, 62, 68)

            if t in ("R", "G", "B", "Y"):
                fill = COLOR_FILL[t]
            if t in ("r", "g", "b", "y"):
                fill = tuple(max(0, c - 60) for c in COLOR_FILL[t.upper()])
            if t == "S":
                fill = (100, 225, 180)
            if t == "E":
                fill = (240, 225, 120)

            draw.rectangle((left, top, right, bottom), fill=fill)

            if t in ("R", "G", "B", "Y", "r", "g", "b", "y", "S", "E"):
                draw.text((left + 10, top + 8), t, fill=(12, 12, 12))

    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Graph dungeon prototype: generate, solve, and render GIF.")
    p.add_argument("--seed", type=int, default=7, help="Random seed.")
    p.add_argument("--rooms", type=int, default=8, help="Number of rooms in room-graph tree.")
    p.add_argument("--output-prefix", type=str, default="generated_dungeon", help="Output file prefix.")
    p.add_argument("--frame-ms", type=int, default=90, help="GIF frame duration in ms.")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    dungeon = generate_dungeon(seed=args.seed, num_rooms=max(4, args.rooms))
    result = solve_dungeon(dungeon)
    if not result.get("solvable"):
        raise SystemExit(f"Generated dungeon is unsolvable: {result.get('reason')}")

    prefix = args.output_prefix
    out_png = Path(f"{prefix}_level.png")
    out_gif = Path(f"{prefix}_route_scratch.gif")
    out_sheet = Path(f"{prefix}_path_icons_scratch.png")

    render_level_png(dungeon, out_png)
    create_path_icon_sheet(out_png, result["positions"], out_sheet, title="Generated Dungeon Path (step order)")
    render_route_gif(out_png, result["positions"], out_gif, frame_ms=max(20, args.frame_ms))

    print(f"Seed: {args.seed}")
    print(f"Rooms: {len(dungeon['rooms'])}")
    print(f"Locks: {len(dungeon['locks'])}")
    print(f"Keys: {len(dungeon['keys'])}")
    print(f"Moves: {result['moves']}")
    print(f"States explored: {result['states_explored']}")
    print(f"Level PNG: {out_png}")
    print(f"Path icons: {out_sheet}")
    print(f"Route GIF: {out_gif}")


if __name__ == "__main__":
    main()
