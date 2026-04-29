#!/usr/bin/env python3
"""Generate, solve, and render a minimal 2-room graph demo.

Graph model:
- Node 0: start room with one chip
- Node 1: exit room
- Edge: socket/gate that requires the chip to be collected before traversal

The rendered level uses the Chip's Challenge sprite tileset from the extracted
wiki assets directory.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH = 32
HEIGHT = 16
TILE = 32
ROOM_W = 13
CORRIDOR_W = 2
ROOM0_X0 = 1
ROOM1_X0 = ROOM0_X0 + ROOM_W + CORRIDOR_W

SPRITE_DIR = Path(
    "/home/nabeel/chips-challenge-2/DAT - The Chip's Challenge Wiki - The Chip's Challenge Database that anyone can edit!_files"
)


@dataclass(frozen=True)
class Node:
    id: int
    name: str
    x0: int
    y0: int
    w: int
    h: int


@dataclass(frozen=True)
class Edge:
    u: int
    v: int
    requires_all_chips: bool
    socket_pos: int


def pos_to_xy(pos: int) -> tuple[int, int]:
    return pos % WIDTH, pos // WIDTH


def xy_to_pos(x: int, y: int) -> int:
    return y * WIDTH + x


def load_sprite(filename: str, tile_size: int = TILE) -> Image.Image | None:
    path = SPRITE_DIR / filename
    if not path.exists():
        return None
    image = Image.open(path).convert("RGBA")
    if image.size != (tile_size, tile_size):
        image = image.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
    return image


def load_sprites() -> dict[str, Image.Image | None]:
    return {
        "floor": load_sprite("Floor.png"),
        "wall": load_sprite("Wall.png"),
        "socket": load_sprite("Socket.png"),
        "exit": load_sprite("Exit.png"),
        "chip": load_sprite("Computer_chip.png"),
        "start": load_sprite("Chip_N.png"),
        "avatar_n": load_sprite("Chip_N.png"),
        "avatar_s": load_sprite("Chip_S.png"),
        "avatar_e": load_sprite("Chip_E.png"),
        "avatar_w": load_sprite("Chip_W.png"),
    }


def build_graph() -> tuple[list[Node], list[Edge], dict[str, int]]:
    nodes = [
        Node(0, "start_room", ROOM0_X0, 1, ROOM_W, 10),
        Node(1, "exit_room", ROOM1_X0, 1, ROOM_W, 10),
    ]

    socket_x = ROOM0_X0 + ROOM_W
    socket_y = 5
    socket_pos = xy_to_pos(socket_x, socket_y)
    edges = [Edge(0, 1, True, socket_pos)]

    start = xy_to_pos(ROOM0_X0 + 1, 5)
    chip = xy_to_pos(ROOM0_X0 + 4, 5)
    exit_pos = xy_to_pos(ROOM1_X0 + 5, 5)

    meta = {
        "start": start,
        "chip": chip,
        "exit": exit_pos,
        "socket": socket_pos,
    }
    return nodes, edges, meta


def build_tile_map(meta: dict[str, int]) -> list[int]:
    tiles = [0x01] * (WIDTH * HEIGHT)

    for y in range(1, 11):
        for x in range(ROOM0_X0, ROOM0_X0 + ROOM_W):
            tiles[xy_to_pos(x, y)] = 0x00
        for x in range(ROOM1_X0, ROOM1_X0 + ROOM_W):
            tiles[xy_to_pos(x, y)] = 0x00

    for x in range(ROOM0_X0 + ROOM_W, ROOM1_X0):
        tiles[xy_to_pos(x, 5)] = 0x00

    tiles[meta["start"]] = 0x6C
    tiles[meta["chip"]] = 0x02
    tiles[meta["socket"]] = 0x21
    tiles[meta["exit"]] = 0x15
    return tiles


def solve_graph(nodes: list[Node], edges: list[Edge], meta: dict[str, int], tiles: list[int]) -> dict:
    del nodes, edges

    start = meta["start"]
    chip_pos = meta["chip"]
    exit_pos = meta["exit"]
    socket_pos = meta["socket"]

    start_state = (start, 0)
    q = deque([start_state])
    parent = {start_state: None}
    move_taken = {start_state: None}
    seen = {start_state}

    def passable(pos: int, has_chip: int) -> bool:
        tile = tiles[pos]
        if tile == 0x01:
            return False
        if pos == socket_pos and not has_chip:
            return False
        return True

    dirs = [(-1, 0, "L"), (1, 0, "R"), (0, -1, "U"), (0, 1, "D")]
    goal_state = None

    while q:
        pos, has_chip = q.popleft()
        if pos == exit_pos and has_chip:
            goal_state = (pos, has_chip)
            break

        x, y = pos_to_xy(pos)
        for dx, dy, step in dirs:
            nx, ny = x + dx, y + dy
            if nx < 0 or nx >= WIDTH or ny < 0 or ny >= HEIGHT:
                continue
            npos = xy_to_pos(nx, ny)
            nhas_chip = has_chip or (npos == chip_pos)
            if not passable(npos, nhas_chip):
                continue
            nstate = (npos, int(nhas_chip))
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = (pos, has_chip)
            move_taken[nstate] = step
            q.append(nstate)

    if goal_state is None:
        return {"solvable": False}

    positions = []
    cur = goal_state
    while cur is not None:
        positions.append(cur[0])
        cur = parent[cur]
    positions.reverse()

    moves = []
    cur = goal_state
    while parent[cur] is not None:
        moves.append(move_taken[cur])
        cur = parent[cur]
    moves.reverse()

    return {
        "solvable": True,
        "positions": positions,
        "moves": "".join(moves),
        "expanded_states": len(seen),
    }


def render_level_png(tiles: list[int], meta: dict[str, int], out_path: Path) -> None:
    sprites = load_sprites()
    img = Image.new("RGBA", (WIDTH * TILE, HEIGHT * TILE), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    for y in range(HEIGHT):
        for x in range(WIDTH):
            pos = xy_to_pos(x, y)
            tile = tiles[pos]
            left, top = x * TILE, y * TILE
            sprite = sprites["wall"] if tile == 0x01 else sprites["floor"]
            if sprite is not None:
                img.alpha_composite(sprite, (left, top))
            else:
                draw.rectangle((left, top, left + TILE - 1, top + TILE - 1), fill=(30, 30, 34) if tile == 0x01 else (186, 186, 186))

    for pos, sprite_name, fallback_color in [
        (meta["start"], "start", (80, 220, 180)),
        (meta["chip"], "chip", (235, 200, 55)),
        (meta["socket"], "socket", (180, 70, 70)),
        (meta["exit"], "exit", (245, 220, 120)),
    ]:
        left = (pos % WIDTH) * TILE
        top = (pos // WIDTH) * TILE
        sprite = sprites[sprite_name]
        if sprite is not None:
            img.alpha_composite(sprite, (left, top))
        else:
            cx = left + TILE // 2
            cy = top + TILE // 2
            r = 11
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fallback_color, outline=(0, 0, 0), width=2)

    draw.text((ROOM0_X0 * TILE + 10, 10), "Room 0", fill=(255, 255, 255))
    draw.text((ROOM1_X0 * TILE + 10, 10), "Room 1", fill=(255, 255, 255))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path)


def render_demo_gif(level_png: Path, positions: list[int], meta: dict[str, int], out_path: Path, frame_ms: int = 120) -> None:
    sprites = load_sprites()
    base = Image.open(level_png).convert("RGBA")
    frames: list[Image.Image] = []
    chip_collected = False
    socket_cleared = False

    for step, pos in enumerate(positions):
        frame = base.copy()
        draw = ImageDraw.Draw(frame)

        # Clear starting position once we leave it
        if step > 0:
            start_x, start_y = pos_to_xy(meta["start"])
            left, top = start_x * TILE, start_y * TILE
            sprite = sprites["floor"]
            if sprite is not None:
                frame.alpha_composite(sprite, (left, top))
            else:
                draw.rectangle((left, top, left + TILE - 1, top + TILE - 1), fill=(186, 186, 186))

        # Check if we're collecting the chip
        if not chip_collected and pos == meta["chip"]:
            chip_collected = True

        # Clear the chip once it's been collected
        if chip_collected:
            chip_x, chip_y = pos_to_xy(meta["chip"])
            left, top = chip_x * TILE, chip_y * TILE
            sprite = sprites["floor"]
            if sprite is not None:
                frame.alpha_composite(sprite, (left, top))
            else:
                draw.rectangle((left, top, left + TILE - 1, top + TILE - 1), fill=(186, 186, 186))

        # Check if we're stepping on the socket
        if pos == meta["socket"]:
            socket_cleared = True

        # Clear the socket if we've stepped on it at any point
        if socket_cleared:
            socket_x, socket_y = pos_to_xy(meta["socket"])
            left, top = socket_x * TILE, socket_y * TILE
            sprite = sprites["floor"]
            if sprite is not None:
                frame.alpha_composite(sprite, (left, top))
            else:
                draw.rectangle((left, top, left + TILE - 1, top + TILE - 1), fill=(186, 186, 186))

        for path_pos in positions[: step + 1]:
            x, y = pos_to_xy(path_pos)
            left, top = x * TILE, y * TILE
            draw.rectangle((left + 11, top + 11, left + TILE - 11, top + TILE - 11), fill=(0, 160, 255, 160))

        # Determine direction of movement and pick sprite
        avatar_sprite = sprites["avatar_e"]
        if step > 0:
            prev_x, prev_y = pos_to_xy(positions[step - 1])
            curr_x, curr_y = pos_to_xy(pos)
            dx, dy = curr_x - prev_x, curr_y - prev_y
            
            if dx > 0:
                avatar_sprite = sprites.get("avatar_e") or sprites["start"]
            elif dx < 0:
                avatar_sprite = sprites.get("avatar_w") or sprites["start"]
            elif dy > 0:
                avatar_sprite = sprites.get("avatar_s") or sprites["start"]
            elif dy < 0:
                avatar_sprite = sprites.get("avatar_n") or sprites["start"]
        
        x, y = pos_to_xy(pos)
        left, top = x * TILE, y * TILE
        if avatar_sprite is not None:
            frame.alpha_composite(avatar_sprite, (left, top))
        else:
            draw.ellipse((left + 6, top + 6, left + TILE - 6, top + TILE - 6), outline=(255, 255, 0), width=3)

        draw.rectangle((4, 4, 140, 24), fill=(0, 0, 0, 180))
        draw.text((8, 8), f"step {step}", fill=(255, 255, 255))

        frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out_path, save_all=True, append_images=frames[1:], duration=frame_ms, loop=0, disposal=2)


def main() -> None:
    nodes, edges, meta = build_graph()
    tiles = build_tile_map(meta)
    result = solve_graph(nodes, edges, meta, tiles)
    if not result.get("solvable"):
        raise SystemExit("Demo graph was not solvable.")

    out_png = Path("two_room_chip_lock_level.png")
    out_gif = Path("two_room_chip_lock_route.gif")
    render_level_png(tiles, meta, out_png)
    render_demo_gif(out_png, result["positions"], meta, out_gif)

    print("=== Graph ===")
    print(f"Nodes: {len(nodes)}")
    print(f"Edges: {len(edges)}")
    print(f"Edge 0->1 requires all chips: {edges[0].requires_all_chips}")
    print()
    print("=== Solve ===")
    print(f"Moves: {len(result['moves'])}")
    print(f"Path: {result['moves']}")
    print(f"Expanded states: {result['expanded_states']}")
    print()
    print(f"Level PNG: {out_png}")
    print(f"Route GIF: {out_gif}")


if __name__ == "__main__":
    main()
