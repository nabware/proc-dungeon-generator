#!/usr/bin/env python3
"""Wrapper to render a level GIF from a solved path."""

import argparse
from pathlib import Path
import sys

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from graph_solver_scratch import (
    load_level_by_number,
    find_start_position,
    solve_with_chip_state,
    pos_to_xy,
    resolve_level_image_path,
)

try:
    from path_gif_renderer import render_route_gif
except ImportError as e:
    print(f"Error: Could not import path_gif_renderer. Missing Pillow? {e}")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Render a solved level as an animated GIF.")
    parser.add_argument("--level", type=int, required=True, help="DAT level number to render.")
    parser.add_argument(
        "--dat",
        type=Path,
        default=Path("/home/nabeel/proc-dungeon-generator/CCUP/Apps/Chip's Challenge/CHIPS.DAT"),
        help="Path to CHIPS.DAT.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output GIF path (default: level{N}_route_scratch.gif).",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=None,
        help="Prefix used for output filenames and image auto-discovery.",
    )
    parser.add_argument(
        "--level-image",
        type=Path,
        default=None,
        help="Optional explicit level image path for GIF background.",
    )
    parser.add_argument(
        "--frame-ms",
        type=int,
        default=120,
        help="Milliseconds per frame (default: 120).",
    )
    args = parser.parse_args()

    dat_path = args.dat
    target_level = args.level
    output_prefix = args.output_prefix or f"level{target_level}"
    output_gif = args.output or Path(f"{output_prefix}_route_scratch.gif")
    frame_ms = args.frame_ms

    # Load and solve level
    level_data = load_level_by_number(dat_path, target_level)
    result = solve_with_chip_state(level_data)

    if not result["solvable"]:
        print(f"Level {target_level} is not solvable: {result.get('reason')}")
        sys.exit(1)

    positions = result["positions"]
    print(f"Level {target_level}: {len(positions) - 1} moves")
    print(f"Path: {result['path']}")

    # Try to render GIF
    level_img_path = resolve_level_image_path(
        target_level,
        dat_path,
        output_prefix,
        args.level_image,
    )
    if not level_img_path.exists():
        print(f"Error: {level_img_path} not found. Cannot render GIF.")
        sys.exit(1)

    try:
        render_route_gif(
            level_img_path,
            positions,
            output_gif,
            frame_ms=frame_ms,
            dat_path=dat_path,
            level_number=target_level,
        )
        print(f"GIF written to {output_gif}")
    except Exception as e:
        print(f"Error rendering GIF: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
