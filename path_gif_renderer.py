#!/usr/bin/env python3
"""Render an animated GIF of a route over a level image.

Usage examples:
- Explicit positions:
  python path_gif_renderer.py --level-image level1.png --out path.gif --positions 463,495,527

- Start + moves:
  python path_gif_renderer.py --level-image level1.png --out path.gif --start 463 --moves DDRRULL
"""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow is required. Install with: pip install pillow") from exc

from chips_level_renderer import effective_tile_id, load_dat_file

START_IDS = {0x6C, 0x6D, 0x6E, 0x6F}
CHIP_IDS = {0x02, 0x20}
KEY_IDS = {0x64, 0x65, 0x66, 0x67}
LOCK_IDS = {0x16, 0x17, 0x18, 0x19}
SOCKET_IDS = {0x21, 0x22}
BOOT_IDS = {0x68, 0x69, 0x6A, 0x6B}  # Flippers, Fire, Ice, Suction


def pos_to_xy(pos: int, width: int = 32) -> tuple[int, int]:
    return (pos % width, pos // width)


def positions_from_moves(start_pos: int, moves: str, width: int = 32, height: int = 32) -> list[int]:
    """Build visited positions from a start tile and move string."""
    x, y = pos_to_xy(start_pos, width)
    positions = [start_pos]

    delta = {
        "L": (-1, 0),
        "R": (1, 0),
        "U": (0, -1),
        "D": (0, 1),
    }

    for i, step in enumerate(moves, start=1):
        if step not in delta:
            raise ValueError(f"Invalid move '{step}' at index {i - 1}. Use only L/R/U/D.")

        dx, dy = delta[step]
        x += dx
        y += dy
        if x < 0 or x >= width or y < 0 or y >= height:
            raise ValueError(f"Move '{step}' at index {i - 1} went out of bounds.")

        positions.append(y * width + x)

    return positions


def parse_positions(raw: str) -> list[int]:
    values = [v.strip() for v in raw.split(",") if v.strip()]
    if not values:
        raise ValueError("No positions provided.")
    return [int(v) for v in values]


def infer_direction(prev_pos: int, cur_pos: int, width: int = 32) -> str:
    px, py = pos_to_xy(prev_pos, width)
    cx, cy = pos_to_xy(cur_pos, width)
    if cx > px:
        return "E"
    if cx < px:
        return "W"
    if cy > py:
        return "S"
    if cy < py:
        return "N"
    return "S"


def load_chip_sprites(tile_size: int = 32) -> dict[str, Image.Image]:
    """Load directional Chip sprites from the extracted wiki image folder."""
    root = Path("/home/nabeel/proc-dungeon-generator")
    sprite_dir = next(iter(root.glob("*_files")), None)
    if sprite_dir is None:
        return {}

    names = {
        "N": "Chip_N.png",
        "S": "Chip_S.png",
        "E": "Chip_E.png",
        "W": "Chip_W.png",
    }

    sprites: dict[str, Image.Image] = {}
    for direction, filename in names.items():
        path = sprite_dir / filename
        if path.exists():
            sprites[direction] = Image.open(path).convert("RGBA").resize((tile_size, tile_size), Image.Resampling.LANCZOS)
    return sprites


def load_floor_sprite(tile_size: int = 32) -> Image.Image | None:
    root = Path("/home/nabeel/proc-dungeon-generator")
    sprite_dir = next(iter(root.glob("*_files")), None)
    if sprite_dir is None:
        return None

    path = sprite_dir / "Floor.png"
    if not path.exists():
        return None
    return Image.open(path).convert("RGBA").resize((tile_size, tile_size), Image.Resampling.LANCZOS)


def load_level_quiet(dat_path: Path, level_number: int) -> dict:
    """Load one level from DAT without parser console spam."""
    with io.StringIO() as sink, redirect_stdout(sink):
        levels = load_dat_file(str(dat_path))

    if level_number < 1 or level_number > len(levels):
        raise ValueError(f"level_number must be in 1..{len(levels)}")
    return levels[level_number - 1]


def render_route_gif(
    level_image_path: Path,
    positions: list[int],
    out_path: Path,
    tile_size: int = 32,
    frame_ms: int = 120,
    loop: int = 0,
    dat_path: Path | None = None,
    level_number: int = 1,
    level_data: dict | None = None,
) -> None:
    """Render an animated GIF showing each step over the full level map."""
    if not positions:
        raise ValueError("Positions list is empty.")

    base = Image.open(level_image_path).convert("RGBA")
    world = base.copy()
    chip_sprites = load_chip_sprites(tile_size)
    floor_sprite = load_floor_sprite(tile_size)
    frames: list[Image.Image] = []
    trail_margin = max(1, int(round(tile_size * 11 / 32)))

    tile_by_pos: dict[int, int] = {}
    if level_data is not None:
        tile_by_pos = {pos: effective_tile_id(level_data, pos) for pos in range(32 * 32)}
    elif dat_path is not None:
        level = load_level_quiet(dat_path, level_number)
        tile_by_pos = {pos: effective_tile_id(level, pos) for pos in range(32 * 32)}

    # Keep a visible trail so each frame represents cumulative state.
    for step, pos in enumerate(positions):
        # Update world state before rendering this frame.
        if step > 0 and floor_sprite is not None and tile_by_pos:
            prev = positions[step - 1]
            prev_tile = tile_by_pos.get(prev)

            # Remove start sprite once we have moved away.
            if prev_tile in START_IDS:
                px, py = pos_to_xy(prev, 32)
                world.alpha_composite(floor_sprite, (px * tile_size, py * tile_size))
                tile_by_pos[prev] = 0x00

        if floor_sprite is not None and tile_by_pos:
            cur_tile = tile_by_pos.get(pos)
            # Chips, keys, locks, sockets, and boots are cleared after first visit.
            if cur_tile in CHIP_IDS or cur_tile in KEY_IDS or cur_tile in LOCK_IDS or cur_tile in SOCKET_IDS or cur_tile in BOOT_IDS:
                cx0, cy0 = pos_to_xy(pos, 32)
                world.alpha_composite(floor_sprite, (cx0 * tile_size, cy0 * tile_size))
                tile_by_pos[pos] = 0x00

        frame = world.copy()
        draw = ImageDraw.Draw(frame)

        # Draw trail up to current step.
        for p in positions[: step + 1]:
            x, y = pos_to_xy(p, 32)
            left = x * tile_size
            top = y * tile_size
            right = left + tile_size - 1
            bottom = top + tile_size - 1
            draw.rectangle(
                (
                    left + trail_margin,
                    top + trail_margin,
                    right - trail_margin,
                    bottom - trail_margin,
                ),
                fill=(0, 160, 255, 180),
            )

        # Draw moving Chip sprite when assets are available.
        cx, cy = pos_to_xy(pos, 32)
        cleft = cx * tile_size
        ctop = cy * tile_size
        cright = cleft + tile_size - 1
        cbottom = ctop + tile_size - 1
        direction = "S" if step == 0 else infer_direction(positions[step - 1], pos)
        sprite = chip_sprites.get(direction)
        if sprite is not None:
            frame.alpha_composite(sprite, (cleft, ctop))
        else:
            draw.ellipse((cleft + 6, ctop + 6, cright - 6, cbottom - 6), outline=(255, 255, 0, 255), width=3)

        # Step badge in upper-left corner.
        draw.rectangle((4, 4, 120, 24), fill=(0, 0, 0, 180))
        draw.text((8, 8), f"step: {step} dir:{direction}", fill=(255, 255, 255, 255))

        frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=frame_ms,
        loop=loop,
        optimize=False,
        disposal=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render animated route GIF over a level map.")
    parser.add_argument("--level-image", required=True, help="Path to rendered level image, for example level1.png")
    parser.add_argument("--out", required=True, help="Output GIF path")
    parser.add_argument("--positions", help="Comma-separated position indices, for example 463,495,527")
    parser.add_argument("--start", type=int, help="Start position index when using --moves")
    parser.add_argument("--moves", help="Route moves as L/R/U/D string when using --start")
    parser.add_argument("--frame-ms", type=int, default=120, help="Frame duration in milliseconds")
    parser.add_argument("--dat-path", help="Optional CHIPS.DAT path to simulate tile state changes")
    parser.add_argument("--level-number", type=int, default=1, help="1-based level number for --dat-path")
    args = parser.parse_args()

    if args.positions:
        positions = parse_positions(args.positions)
    elif args.start is not None and args.moves is not None:
        positions = positions_from_moves(args.start, args.moves)
    else:
        raise SystemExit("Provide either --positions OR both --start and --moves.")

    render_route_gif(
        level_image_path=Path(args.level_image),
        positions=positions,
        out_path=Path(args.out),
        frame_ms=max(20, args.frame_ms),
        dat_path=Path(args.dat_path) if args.dat_path else None,
        level_number=args.level_number,
    )
    print(f"Wrote route GIF: {args.out}")


if __name__ == "__main__":
    main()
