Chip's Challenge Level Renderer

Purpose
- Central renderer for DAT levels and in-memory level dicts.

Key functions (in `chips_level_renderer.py`)

- `render_level(level, tile_size=32, images_path=None)`
  - Render an in-memory `level` dict (with `layer1` and `layer2`) to a PIL Image.

- `render_level_to_path(level, out_path, tile_size=32, images_path=None)`
  - Render a `level` dict and save the PNG to `out_path`.
  - Use this when you already have a parsed `level` object in memory.

- `load_level_by_number(dat_path: Path, target_number: int) -> dict`
  - Parse a DAT file and return the requested level as a `level` dict.
  - Keeps DAT parsing colocated with the renderer so callers need only import this module for rendering DAT levels.

- `render_dat_level(dat_path: Path, level_number: int, out_path, tile_size=32, images_path=None)`
  - Convenience helper that loads a level from the DAT file and writes the rendered PNG to `out_path`.
  - Preferred when you want to render a named level from a DAT pack in a single call.

Images / Tileset
- The renderer expects a tileset folder extracted from the Chip's Challenge Wiki HTML mirror named exactly:
  `DAT - The Chip's Challenge Wiki - The Chip's Challenge Database that anyone can edit!_files`
- The repo's `.gitignore` includes a specific unignore entry so this folder is tracked.
- Default `images_path` in `render_level()` points to this folder inside the repo root; pass `images_path` to override.

Recommended usage

- Render DAT level 1 from CHIPS.DAT:

```bash
source venv/bin/activate
python3 - <<'PY'
from pathlib import Path
from chips_level_renderer import render_dat_level
render_dat_level(Path('CCUP/Apps/Chip\'s Challenge/CHIPS.DAT'), 1, Path('level1.png'), tile_size=32)
PY
```

- Render Key Pyramid (CCLP1.dat level 1):

```bash
source venv/bin/activate
python3 - <<'PY'
from pathlib import Path
from chips_level_renderer import render_dat_level
render_dat_level(Path('CCUP/Level Sets/CCLP1/data/CCLP1.dat'), 1, Path('key_pyramid_level.png'), tile_size=32)
PY
```

Why centralize
- Single place for image-size, images_path, caching, and tile filename mapping.
- Makes it easy to change tile_size or tile filename mappings without editing many scripts.
- Other scripts should call `render_level_to_path()` or `render_dat_level()` instead of using ad-hoc PIL code.

Notes for future sessions
- If you move or rename the tileset folder, update `.gitignore` and `images_path` default in `chips_level_renderer.py`.
- For automated builds, prefer `render_dat_level()` to keep scripts idempotent.

