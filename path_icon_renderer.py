#!/usr/bin/env python3
"""Render a path icon sheet from route data.

Usage examples:
- Pass explicit positions:
  python path_icon_renderer.py --level-image level1.png --out path_icons.png --positions 463,495,527

- Pass start and moves (L/R/U/D):
  python path_icon_renderer.py --level-image level1.png --out path_icons.png --start 463 --moves DDRRULL
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow is required. Install with: pip install pillow") from exc


def pos_to_xy(pos: int, width: int = 32) -> tuple[int, int]:
    return (pos % width, pos // width)


def positions_from_moves(start_pos: int, moves: str, width: int = 32, height: int = 32) -> list[int]:
    """Build visited positions from a start tile and a move string.

    The returned list includes the start position as step 0.
    """
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


def create_path_icon_sheet(
    level_image_path: Path,
    positions: list[int],
    out_path: Path,
    tile_size: int = 32,
    columns: int = 16,
    title: str = "Path Tiles (step order)",
) -> None:
    """Crop each visited tile from the level image and write an icon sheet."""
    level_img = Image.open(level_image_path).convert("RGB")

    step_count = len(positions)
    rows = (step_count + columns - 1) // columns
    header_h = 28
    sheet_w = columns * tile_size
    sheet_h = rows * tile_size + header_h

    sheet = Image.new("RGB", (sheet_w, sheet_h), (20, 20, 24))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), title, fill=(230, 230, 240))

    for idx, pos in enumerate(positions):
        gx, gy = pos_to_xy(pos, 32)
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

        draw.rectangle((dx, dy, dx + 16, dy + 11), fill=(0, 0, 0))
        draw.text((dx + 1, dy), str(idx), fill=(255, 255, 255))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a path icon sheet from route data.")
    parser.add_argument("--level-image", required=True, help="Path to rendered level image (for example level1.png).")
    parser.add_argument("--out", required=True, help="Output PNG path.")
    parser.add_argument("--positions", help="Comma-separated position indices, for example 463,495,527")
    parser.add_argument("--start", type=int, help="Start position index when using --moves")
    parser.add_argument("--moves", help="Route moves as L/R/U/D string when using --start")
    parser.add_argument("--title", default="Path Tiles (step order)", help="Header title for the image")
    args = parser.parse_args()

    if args.positions:
        positions = parse_positions(args.positions)
    elif args.start is not None and args.moves is not None:
        positions = positions_from_moves(args.start, args.moves)
    else:
        raise SystemExit("Provide either --positions OR both --start and --moves.")

    create_path_icon_sheet(
        level_image_path=Path(args.level_image),
        positions=positions,
        out_path=Path(args.out),
        title=args.title,
    )
    print(f"Wrote path icon sheet: {args.out}")


if __name__ == "__main__":
    main()
