# Chips Challenge workflow instructions

## Environment (always required)
- Always activate the project virtual environment before any Python command:
  - `source venv/bin/activate`
- Run all solver/render commands from the repo root.

## Solve levels
- Use `graph_solver_scratch.py` as the default solver entrypoint.
- Standard command pattern:
  - `source venv/bin/activate && python3 graph_solver_scratch.py --dat "<dat_path>" --level <n> --output-prefix <name>`

## Regenerate route GIFs and path sheets
- Preferred path: run the solver command above (it also writes path sheet + GIF when Pillow deps are available).
- Wrapper option:
  - `source venv/bin/activate && python3 render_level_gif.py --dat "<dat_path>" --level <n> --output-prefix <name>`

## Level image selection rules
- Background image resolution now follows this order:
  1. `--level-image <path>` when provided
  2. `<output-prefix>_level.png`
  3. `<output-prefix>.png`
  4. `level<n>.png`
- For Key Pyramid, always use output prefix `key_pyramid` (or pass `--level-image key_pyramid_level.png`) so it does not accidentally use `level1.png`.

## Known good Key Pyramid command
- `source venv/bin/activate && python3 graph_solver_scratch.py --dat "./CCUP/Level Sets/CCLP1/data/CCLP1.dat" --level 1 --output-prefix key_pyramid`
