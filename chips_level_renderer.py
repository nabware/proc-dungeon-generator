#!/usr/bin/env python3
"""
Chip's Challenge DAT file parser and level renderer
Parses DAT format and generates PNG images of levels using actual tile sprites
"""

import struct
from collections import deque
from pathlib import Path
from PIL import Image

# Tile encoding - maps byte values to tile names and image filenames
TILE_NAMES = {
    # Row 0x_0
    0x00: ("Floor", "Floor.png"),
    0x10: ("Wall", "Wall.png"),
    0x20: ("Computer Chip", "Computer_chip.png"),
    0x30: ("Water", "Water.png"),
    0x40: ("Bug (N)", "Bug_N.png"),
    0x50: ("Glider (N)", "Glider_N.png"),
    0x60: ("Paramecium (N)", "Paramecium_NS.png"),
    
    # Row 0x_1
    0x01: ("Wall", "Wall.png"),
    0x11: ("Clone Block (S)", "Clone_block_S.png"),
    0x21: ("Socket", "Socket.png"),
    0x31: ("Green Button", "Green_button.png"),
    0x41: ("Bug (W)", "Bug_W.png"),
    0x51: ("Glider (W)", "Glider_W.png"),
    0x61: ("Paramecium (W)", "Paramecium_WE.png"),
    
    # Row 0x_2
    0x02: ("Computer Chip", "Computer_chip.png"),
    0x12: ("Force Floor (N)", "Force_floor_N.png"),
    0x22: ("Socket", "Socket.png"),
    0x32: ("Red Button", "Red_button.png"),
    0x42: ("Bug (S)", "Bug_S.png"),
    0x52: ("Glider (S)", "Glider_S.png"),
    0x62: ("Paramecium (S)", "Paramecium_NS.png"),
    
    # Row 0x_3
    0x03: ("Water", "Water.png"),
    0x13: ("Force Floor (E)", "Force_floor_E.png"),
    0x23: ("Green Button", "Green_button.png"),
    0x33: ("Drowned Chip", "Drowned_Chip.png"),
    0x43: ("Bug (E)", "Bug_E.png"),
    0x53: ("Glider (E)", "Glider_E.png"),
    0x63: ("Paramecium (E)", "Paramecium_WE.png"),
    
    # Row 0x_4
    0x04: ("Fire", "Fire.png"),
    0x14: ("Force Floor (W)", "Force_floor_W.png"),
    0x24: ("Red Button", "Red_button.png"),
    0x34: ("Burned Chip", "Burned_Chip.png"),
    0x44: ("Fireball (N)", "Fireball.png"),
    0x54: ("Teeth (N)", "Teeth_N.png"),
    0x64: ("Blue Key", "Blue_key.png"),
    
    # Row 0x_5
    0x05: ("Invisible Wall", "Invisible_wall.png"),
    0x15: ("Exit", "Exit.png"),
    0x25: ("Toggle Wall (Closed)", "Toggle_wall_Closed.png"),
    0x35: ("Drowned Chip", "Drowned_Chip.png"),
    0x45: ("Fireball (W)", "Fireball.png"),
    0x55: ("Teeth (W)", "Teeth_W.png"),
    0x65: ("Red Key", "Red_key.png"),
    
    # Row 0x_6
    0x06: ("Thin Wall (N)", "Thin_wall_N.png"),
    0x16: ("Blue Lock", "Blue_lock.png"),
    0x26: ("Toggle Wall (Open)", "Toggle_wall_Open.png"),
    0x36: ("Recessed Wall", "Recessed_wall.png"),
    0x46: ("Fireball (S)", "Fireball.png"),
    0x56: ("Teeth (S)", "Teeth_S.png"),
    0x66: ("Green Key", "Green_key.png"),
    
    # Row 0x_7
    0x07: ("Thin Wall (W)", "Thin_wall_W.png"),
    0x17: ("Red Lock", "Red_lock.png"),
    0x27: ("Brown Button", "Brown_button.png"),
    0x37: ("Hint", "Hint.png"),
    0x47: ("Fireball (E)", "Fireball.png"),
    0x57: ("Teeth (E)", "Teeth_E.png"),
    0x67: ("Yellow Key", "Yellow_key.png"),
    
    # Row 0x_8
    0x08: ("Thin Wall (S)", "Thin_wall_S.png"),
    0x18: ("Green Lock", "Green_lock.png"),
    0x28: ("Teleport", "Teleport.png"),
    0x38: ("Bomb", "Bomb.png"),
    0x48: ("Pink Ball (N)", "Pink_ball.png"),
    0x58: ("Walker (N)", "Walker_NS.png"),
    0x68: ("Flippers", "Flippers.png"),
    
    # Row 0x_9
    0x09: ("Thin Wall (E)", "Thin_wall_E.png"),
    0x19: ("Yellow Lock", "Yellow_lock.png"),
    0x29: ("Bomb", "Bomb.png"),
    0x39: ("Fake Exit", "Exit2.png"),
    0x49: ("Pink Ball (W)", "Pink_ball.png"),
    0x59: ("Walker (W)", "Walker_WE.png"),
    0x69: ("Fire Boots", "Fire_boots.png"),
    
    # Row 0x_A
    0x0A: ("Dirt Block", "Block.png"),
    0x1A: ("Ice Corner (NW)", "Ice_NW.png"),
    0x2A: ("Bomb", "Bomb.png"),
    0x3A: ("Fake Exit", "Exit3.png"),
    0x4A: ("Pink Ball (S)", "Pink_ball.png"),
    0x5A: ("Walker (S)", "Walker_NS.png"),
    0x6A: ("Ice Skates", "Ice_skates.png"),
    
    # Row 0x_B
    0x0B: ("Dirt", "Dirt.png"),
    0x1B: ("Ice Corner (NE)", "Ice_NE.png"),
    0x2B: ("Trap", "Trap.png"),
    0x3B: ("Fake Exit", "Exit2.png"),
    0x4B: ("Pink Ball (E)", "Pink_ball.png"),
    0x5B: ("Walker (E)", "Walker_WE.png"),
    0x6B: ("Suction Boots", "Suction_boots.png"),
    
    # Row 0x_C
    0x0C: ("Ice", "Ice.png"),
    0x1C: ("Ice Corner (SE)", "Ice_SE.png"),
    0x2C: ("Hidden Wall", "Hidden_wall.png"),
    0x3C: ("Swimming Chip (N)", "Swimming_Chip_N.png"),
    0x4C: ("Tank (N)", "Tank_N.png"),
    0x5C: ("Blob (N)", "Blob.png"),
    0x6C: ("Chip (N)", "Chip_N.png"),
    
    # Row 0x_D
    0x0D: ("Force Floor (S)", "Force_floor_S.png"),
    0x1D: ("Ice Corner (SW)", "Ice_SW.png"),
    0x2D: ("Gravel", "Gravel.png"),
    0x3D: ("Swimming Chip (W)", "Swimming_Chip_W.png"),
    0x4D: ("Tank (W)", "Tank_W.png"),
    0x5D: ("Blob (W)", "Blob.png"),
    0x6D: ("Chip (W)", "Chip_W.png"),
    
    # Row 0x_E
    0x0E: ("Clone Block (N)", "Clone_block_N.png"),
    0x1E: ("Fake Blue Wall", "Blue_wall.png"),
    0x2E: ("Recessed Wall", "Recessed_wall.png"),
    0x3E: ("Swimming Chip (S)", "Swimming_Chip_S.png"),
    0x4E: ("Tank (S)", "Tank_S.png"),
    0x5E: ("Blob (S)", "Blob.png"),
    0x6E: ("Chip (S)", "Chip_S.png"),
    
    # Row 0x_F
    0x0F: ("Clone Block (W)", "Clone_block_W.png"),
    0x1F: ("Real Blue Wall", "Blue_wall.png"),
    0x2F: ("Hint", "Hint.png"),
    0x3F: ("Swimming Chip (E)", "Swimming_Chip_E.png"),
    0x4F: ("Tank (E)", "Tank_E.png"),
    0x5F: ("Blob (E)", "Blob.png"),
    0x6F: ("Chip (E)", "Chip_E.png"),
}


def decode_layer(data):
    """Decode a layer from the DAT file using RLE encoding"""
    tiles = []
    i = 0
    while len(tiles) < 1024:  # 32x32 grid
        if data[i] == 0xFF:
            # RLE encoding: FF count tile_id
            count = data[i + 1]
            tile_id = data[i + 2]
            tiles.extend([tile_id] * count)
            i += 3
        else:
            tiles.append(data[i])
            i += 1
    return tiles[:1024]  # Ensure exactly 1024 tiles


def parse_level(data, offset):
    """Parse a single level from DAT file starting at offset"""
    level_data = {}
    
    # Read level header (8 bytes)
    level_size = struct.unpack_from('<H', data, offset)[0]
    level_data['size'] = level_size
    level_data['number'] = struct.unpack_from('<H', data, offset + 2)[0]
    level_data['time'] = struct.unpack_from('<H', data, offset + 4)[0]
    level_data['chips'] = struct.unpack_from('<H', data, offset + 6)[0]
    
    # Read map encoding type
    map_type = struct.unpack_from('<H', data, offset + 8)[0]
    
    # Read first layer
    layer1_size = struct.unpack_from('<H', data, offset + 10)[0]
    layer1_data = data[offset + 12:offset + 12 + layer1_size]
    level_data['layer1'] = decode_layer(layer1_data)
    
    # Read second layer
    next_offset = offset + 12 + layer1_size
    layer2_size = struct.unpack_from('<H', data, next_offset)[0]
    layer2_data = data[next_offset + 2:next_offset + 2 + layer2_size]
    level_data['layer2'] = decode_layer(layer2_data)
    
    return level_data


def load_dat_file(filepath):
    """Load and parse a Chip's Challenge DAT file"""
    with open(filepath, 'rb') as f:
        data = f.read()
    
    # Check magic number
    magic = struct.unpack_from('<I', data, 0)[0]
    print(f"Magic number: 0x{magic:08X}")
    
    if magic not in [0x0002AAAC, 0x0102AAAC]:
        raise ValueError(f"Invalid DAT file magic number: 0x{magic:08X}")
    
    # Read number of levels
    num_levels = struct.unpack_from('<H', data, 4)[0]
    print(f"Number of levels: {num_levels}")
    
    # Parse levels
    levels = []
    offset = 6
    for i in range(num_levels):
        try:
            level = parse_level(data, offset)
            level['index'] = i + 1
            levels.append(level)
            print(f"Parsed level {level['number']}: time={level['time']}s, chips={level['chips']}")
            offset += level['size'] + 2  # +2 for the size field itself
        except Exception as e:
            print(f"Error parsing level {i+1}: {e}")
            break
    
    return levels


def render_level(level, tile_size=32, images_path=None):
    """Render a level to a PIL Image using actual tile sprites"""
    if images_path is None:
        images_path = Path('/home/nabeel/proc-dungeon-generator/DAT - The Chip\'s Challenge Wiki - The Chip\'s Challenge Database that anyone can edit!_files')
    
    # Load all tile images into cache
    tile_cache = {}
    
    def get_tile_image(filename):
        """Load and cache a tile image, resizing to tile_size"""
        if filename in tile_cache:
            return tile_cache[filename]
        
        try:
            img_path = images_path / filename
            if img_path.exists():
                img = Image.open(img_path)
                # Convert to RGBA to preserve transparency
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                # Resize to tile_size
                img = img.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
                tile_cache[filename] = img
                return img
        except Exception as e:
            print(f"Warning: Could not load {filename}: {e}")
        
        return None
    
    # Create image with RGBA mode for better transparency handling
    width = 32 * tile_size
    height = 32 * tile_size
    img = Image.new('RGBA', (width, height), color=(192, 192, 192, 255))
    
    # Pre-fill background with Floor tiles for proper appearance
    floor_img = get_tile_image("Floor.png")
    if floor_img:
        for y in range(0, height, tile_size):
            for x in range(0, width, tile_size):
                img.paste(floor_img, (x, y), floor_img)
    
    # Draw tiles from layer 1 (bottom layer)
    layer1 = level['layer1']
    for i, tile_id in enumerate(layer1):
        x = (i % 32) * tile_size
        y = (i // 32) * tile_size
        
        if tile_id == 0x00:  # Skip floor, already drawn
            continue
        
        if tile_id in TILE_NAMES:
            filename = TILE_NAMES[tile_id][1]
            tile_img = get_tile_image(filename)
            if tile_img:
                img.paste(tile_img, (x, y), tile_img)
    
    # Draw layer 2 tiles (top layer) - only if not floor
    layer2 = level['layer2']
    for i, tile_id in enumerate(layer2):
        if tile_id != 0x00:  # Skip floor tiles
            x = (i % 32) * tile_size
            y = (i // 32) * tile_size
            
            if tile_id in TILE_NAMES:
                filename = TILE_NAMES[tile_id][1]
                tile_img = get_tile_image(filename)
                if tile_img:
                    img.paste(tile_img, (x, y), tile_img)
    
    # Convert to RGB for final output
    rgb_img = Image.new('RGB', (width, height), (192, 192, 192))
    rgb_img.paste(img, (0, 0), img)
    return rgb_img


def render_level_to_path(level: dict, out_path, tile_size: int = 32, images_path=None):
    """Render an in-memory `level` dict and save it to `out_path`.

    This centralizes image saving so other scripts call a single function.
    """
    img = render_level(level, tile_size=tile_size, images_path=images_path)
    out_path = Path(out_path)
    img.save(out_path)
    return out_path


def load_level_by_number(dat_path: Path, target_number: int) -> dict:
    """Load one level by DAT level number using the local DAT parser.

    This mirrors similar helper in other modules but keeps DAT parsing
    functionality inside this renderer module so callers need not import
    parsing helpers from multiple places.
    """
    levels = load_dat_file(dat_path)
    for lvl in levels:
        if int(lvl.get("number", -1)) == int(target_number):
            return lvl
    raise ValueError(f"Level number {target_number} not found in {dat_path}")


def render_dat_level(dat_path: Path, level_number: int, out_path, tile_size: int = 32, images_path=None):
    """Load a level from a DAT file and render it to `out_path`.

    Uses the local DAT parsing helpers to avoid cross-module imports.
    """
    level = load_level_by_number(dat_path, level_number)
    return render_level_to_path(level, out_path, tile_size=tile_size, images_path=images_path)


def effective_tile_id(level, pos):
    """Return the effective tile ID at pos (top layer wins if not floor)."""
    top = level['layer2'][pos]
    if top != 0x00:
        return top
    return level['layer1'][pos]


def level_to_grid(level, width=32, height=32):
    """Convert a parsed level into a 2D grid of effective tile IDs."""
    grid = []
    for y in range(height):
        row = []
        for x in range(width):
            pos = y * width + x
            row.append(effective_tile_id(level, pos))
        grid.append(row)
    return grid


def build_level_graph(level, width=32, height=32):
    """Build a simple adjacency graph of passable cells for a level.

    This graph is static and ignores dynamic mechanics. It is useful as a first
    representation step before full BFS over inventory/state.
    """
    blocked_ids = {
        0x01, 0x10,  # Wall
        0x05,        # Invisible Wall
        0x0A,        # Dirt Block
        0x16, 0x17, 0x18, 0x19,  # Locks (closed in static graph)
        0x1F,        # Real Blue Wall
        0x21, 0x22,  # Socket
        0x25,        # Toggle Wall (Closed)
        0x2B,        # Trap
        0x2C,        # Hidden Wall
        0x2E,        # Recessed Wall
    }

    hazard_ids = {
        0x03, 0x30,  # Water variants
        0x04,        # Fire
        0x29, 0x2A, 0x38,  # Bomb variants
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

    def is_passable(pos):
        tile = effective_tile_id(level, pos)
        if tile in blocked_ids:
            return False
        if tile in hazard_ids:
            return False
        return True

    graph = {}
    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    for y in range(height):
        for x in range(width):
            pos = y * width + x
            if not is_passable(pos):
                continue

            neighbors = []
            for dx, dy in directions:
                nx = x + dx
                ny = y + dy
                if nx < 0 or nx >= width or ny < 0 or ny >= height:
                    continue
                npos = ny * width + nx
                if is_passable(npos):
                    neighbors.append(npos)

            graph[pos] = neighbors

    return graph


def level_dict_to_graph(level, width=32, height=32):
    """Derive multiple graph views from a level dict.

    Returns a tuple: (tile_graph, room_map, resource_graph)

    - tile_graph: dict[pos, list[pos]] adjacency of passable tiles
    - room_map: list[int] mapping pos -> room_id (or -1 for blocked)
    - resource_graph: dict with lists of resources found (chips, keys, locks, sockets, exits)
    """
    # Tile adjacency
    tile_graph = build_level_graph(level, width=width, height=height)

    # Room segmentation via flood-fill on passable tiles
    room_map = [-1] * (width * height)
    rooms = {}
    room_id = 0

    for pos in range(width * height):
        if pos not in tile_graph:
            continue
        if room_map[pos] != -1:
            continue

        # BFS flood fill
        q = [pos]
        room_map[pos] = room_id
        rooms[room_id] = [pos]
        qi = 0
        while qi < len(q):
            cur = q[qi]
            qi += 1
            for nb in tile_graph.get(cur, []):
                if room_map[nb] == -1:
                    room_map[nb] = room_id
                    rooms[room_id].append(nb)
                    q.append(nb)
        room_id += 1

    # Resource extraction
    def eff(pos):
        return effective_tile_id(level, pos)

    resource_graph = {
        'chips': [],
        'keys': [],
        'locks': [],
        'sockets': [],
        'exits': [],
    }

    for pos in range(width * height):
        t = eff(pos)
        if t in {0x02, 0x20}:
            resource_graph['chips'].append(pos)
        if t in {0x64, 0x65, 0x66, 0x67}:
            resource_graph['keys'].append({'pos': pos, 'tile': t})
        if t in {0x16, 0x17, 0x18, 0x19}:
            resource_graph['locks'].append({'pos': pos, 'tile': t})
        if t in {0x21, 0x22}:
            resource_graph['sockets'].append(pos)
        if t == 0x15:
            resource_graph['exits'].append(pos)

    return tile_graph, room_map, resource_graph


def graph_to_level_dict(node_tile_map, width=32, height=32, number=0, time=0):
    """Convert a mapping of tile positions -> tile IDs into a level dict.

    This is intended for procedural generators that build per-tile assignments.
    Any positions not present in `node_tile_map` are treated as floor (0x00).
    The function returns a minimal level dict compatible with the renderer.
    """
    total = width * height
    layer1 = [0x00] * total
    layer2 = [0x00] * total

    for pos, tile_id in node_tile_map.items():
        if pos < 0 or pos >= total:
            continue
        # Place everything in the top layer by default (generator may decide otherwise)
        layer2[pos] = int(tile_id)

    chips = sum(1 for t in layer1 + layer2 if t in (0x02, 0x20))

    return {
        'size': 0,
        'number': number,
        'time': time,
        'chips': chips,
        'layer1': layer1,
        'layer2': layer2,
    }


def find_tile_positions(level, tile_ids, width=32, height=32):
    """Find positions whose effective tile is in tile_ids."""
    out = []
    for pos in range(width * height):
        if effective_tile_id(level, pos) in tile_ids:
            out.append(pos)
    return out


def pos_to_xy(pos, width=32):
    return (pos % width, pos // width)


def solve_level_bfs(level):
    """Solve a level with BFS using core Chip's Challenge mechanics.

    Modeled mechanics:
    - Movement on a 4-neighbor grid
    - Static walls and hazards are blocked
    - Collectible chips are tracked in state
    - Socket tiles become passable after required chips are collected
    - Exit is considered a win only after required chips are collected

    This is intentionally conservative and targets first-level solvability.
    """
    width = 32
    height = 32
    total_tiles = width * height
    layer1 = level['layer1']
    layer2 = level['layer2']

    # Find Chip start (oriented Chip sprite in DAT encoding)
    start_ids = {0x6C, 0x6D, 0x6E, 0x6F}
    start_pos = None
    for i, tile_id in enumerate(layer2):
        if tile_id in start_ids:
            start_pos = i
            break

    if start_pos is None:
        for i, tile_id in enumerate(layer1):
            if tile_id in start_ids:
                start_pos = i
                break

    if start_pos is None:
        return {
            'solvable': False,
            'reason': 'No Chip start tile found in level.',
            'moves': None,
            'path': None,
        }

    # Collect all chip collectible positions from either layer.
    chip_collectible_ids = {0x02, 0x20}
    chip_positions = []
    for i in range(total_tiles):
        if layer1[i] in chip_collectible_ids or layer2[i] in chip_collectible_ids:
            chip_positions.append(i)

    chip_index = {pos: idx for idx, pos in enumerate(chip_positions)}
    chips_required = int(level.get('chips', 0))

    def cell_tile(pos):
        """Return effective tile at a position (top layer wins if non-floor)."""
        top = layer2[pos]
        return top if top != 0x00 else layer1[pos]

    # Core blocked tiles (conservative set for robust first-level solving).
    blocked_ids = {
        0x01, 0x10,  # Wall
        0x05,        # Invisible Wall
        0x0A,        # Dirt Block
        0x1F,        # Real Blue Wall
        0x25,        # Toggle Wall (Closed)
        0x2B,        # Trap
        0x2C,        # Hidden Wall
        0x2E,        # Recessed Wall
    }

    hazard_ids = {
        0x03,  # Water
        0x30,  # Water variant
        0x04,  # Fire
        0x38, 0x29, 0x2A,  # Bomb variants used by mapping
        0x40, 0x41, 0x42, 0x43,  # Bugs
        0x44, 0x45, 0x46, 0x47,  # Fireballs
        0x48, 0x49, 0x4A, 0x4B,  # Pink balls
        0x4C, 0x4D, 0x4E, 0x4F,  # Tanks
        0x50, 0x51, 0x52, 0x53,  # Gliders
        0x54, 0x55, 0x56, 0x57,  # Teeth
        0x58, 0x59, 0x5A, 0x5B,  # Walkers
        0x5C, 0x5D, 0x5E, 0x5F,  # Blobs
        0x60, 0x61, 0x62, 0x63,  # Paramecia
    }

    # We treat these as exits in the table variants.
    exit_ids = {0x15}

    # Sockets gate progress until enough chips are collected.
    socket_ids = {0x21, 0x22}

    # Keys and locks.
    key_to_idx = {0x64: 0, 0x65: 1, 0x66: 2, 0x67: 3}
    lock_to_idx = {0x16: 0, 0x17: 1, 0x18: 2, 0x19: 3}

    lock_positions = []
    for pos in range(total_tiles):
        t = cell_tile(pos)
        if t in lock_to_idx:
            lock_positions.append(pos)
    lock_pos_to_bit = {pos: idx for idx, pos in enumerate(lock_positions)}

    directions = [
        (-1, 0, 'L'),
        (1, 0, 'R'),
        (0, -1, 'U'),
        (0, 1, 'D'),
    ]

    def is_goal(pos, chip_mask):
        collected = chip_mask.bit_count()
        if collected < chips_required:
            return False
        t = cell_tile(pos)
        return t in exit_ids

    def can_step_on(tile_id, chip_mask, keys, opened_locks_mask, pos):
        collected = chip_mask.bit_count()

        if tile_id in blocked_ids:
            return False
        if tile_id in hazard_ids:
            return False

        # Sockets require required chip count.
        if tile_id in socket_ids and collected < chips_required:
            return False

        if tile_id in lock_to_idx:
            lock_bit = lock_pos_to_bit.get(pos)
            if lock_bit is not None and (opened_locks_mask & (1 << lock_bit)):
                return True

            color_idx = lock_to_idx[tile_id]
            return keys[color_idx] > 0

        return True

    start_mask = 0
    if start_pos in chip_index:
        start_mask |= 1 << chip_index[start_pos]

    # Starting inventory and opened-lock state.
    start_keys = (0, 0, 0, 0)  # blue, red, green, yellow
    start_opened_locks_mask = 0

    start_state = (start_pos, start_mask, start_keys, start_opened_locks_mask)
    queue = deque([start_state])
    seen = {start_state}
    parent = {start_state: None}
    move_taken = {start_state: None}

    goal_state = None

    while queue:
        pos, chip_mask, keys, opened_locks_mask = queue.popleft()

        if is_goal(pos, chip_mask):
            goal_state = (pos, chip_mask, keys, opened_locks_mask)
            break

        x = pos % width
        y = pos // width

        for dx, dy, move_label in directions:
            nx = x + dx
            ny = y + dy
            if nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue

            npos = ny * width + nx
            ntile = cell_tile(npos)
            if not can_step_on(ntile, chip_mask, keys, opened_locks_mask, npos):
                continue

            nmask = chip_mask
            if npos in chip_index:
                nmask |= 1 << chip_index[npos]

            nkeys = list(keys)
            nopened = opened_locks_mask

            # Collect key if present.
            if ntile in key_to_idx:
                nkeys[key_to_idx[ntile]] += 1

            # Spend key and open lock on first entry.
            if ntile in lock_to_idx:
                lock_bit = lock_pos_to_bit.get(npos)
                if lock_bit is not None and not (nopened & (1 << lock_bit)):
                    color_idx = lock_to_idx[ntile]
                    nkeys[color_idx] -= 1
                    nopened |= (1 << lock_bit)

            nstate = (npos, nmask, tuple(nkeys), nopened)
            if nstate in seen:
                continue

            seen.add(nstate)
            parent[nstate] = (pos, chip_mask, keys, opened_locks_mask)
            move_taken[nstate] = move_label
            queue.append(nstate)

    if goal_state is None:
        return {
            'solvable': False,
            'reason': 'No path found to exit after collecting required chips.',
            'moves': None,
            'path': None,
        }

    # Reconstruct path as move letters.
    path = []
    cur = goal_state
    while parent[cur] is not None:
        path.append(move_taken[cur])
        cur = parent[cur]
    path.reverse()

    return {
        'solvable': True,
        'reason': None,
        'moves': len(path),
        'path': ''.join(path),
        'chips_required': chips_required,
        'chips_in_map': len(chip_positions),
    }


def main():
    dat_file = Path('/home/nabeel/proc-dungeon-generator/CCUP/Apps/Chip\'s Challenge/CHIPS.DAT')
    
    # Load the DAT file
    levels = load_dat_file(dat_file)
    
    if levels:
        # CLI:
        #   python chips_level_renderer.py [level_num]            -> render
        #   python chips_level_renderer.py solve [level_num]      -> solve via BFS
        import sys
        args = sys.argv[1:]

        if args and args[0].lower() == 'solve':
            level_num = int(args[1]) if len(args) > 1 else 1
            if level_num <= 0 or level_num > len(levels):
                print(f"Level {level_num} not found. Available levels: 1-{len(levels)}")
                return

            level = levels[level_num - 1]
            print(f"\nSolving level {level['number']} with BFS...")
            result = solve_level_bfs(level)

            if result['solvable']:
                print("Result: SOLVABLE")
                print(f"  Moves: {result['moves']}")
                print(f"  Chips required: {result['chips_required']}")
                print(f"  Chips detected in map: {result['chips_in_map']}")
                print(f"  Path (L/R/U/D): {result['path']}")
            else:
                print("Result: NOT SOLVABLE (under current solver model)")
                print(f"  Reason: {result['reason']}")
            return

        if args and args[0].lower() == 'graph':
            level_num = int(args[1]) if len(args) > 1 else 1
            if level_num <= 0 or level_num > len(levels):
                print(f"Level {level_num} not found. Available levels: 1-{len(levels)}")
                return

            level = levels[level_num - 1]
            grid = level_to_grid(level)
            graph = build_level_graph(level)

            start_ids = {0x6C, 0x6D, 0x6E, 0x6F}
            start_positions = find_tile_positions(level, start_ids)
            exit_positions = find_tile_positions(level, {0x15})
            chip_positions = find_tile_positions(level, {0x02, 0x20})

            edge_count = sum(len(v) for v in graph.values())

            print(f"\nGraph summary for level {level['number']}")
            print(f"  Grid size: {len(grid[0])}x{len(grid)}")
            print(f"  Passable nodes: {len(graph)}")
            print(f"  Directed edges: {edge_count}")
            print(f"  Exit tiles: {len(exit_positions)}")
            print(f"  Chip collectibles detected: {len(chip_positions)}")

            if start_positions:
                sx, sy = pos_to_xy(start_positions[0])
                print(f"  Start: ({sx}, {sy})")
            else:
                print("  Start: not found")

            if exit_positions:
                ex, ey = pos_to_xy(exit_positions[0])
                print(f"  First exit: ({ex}, {ey})")

            return

        level_num = int(args[0]) if args else 1

        if level_num <= len(levels):
            # Render the specified level
            level = levels[level_num - 1]
            print(f"\nRendering level {level['number']} with tile sprites...")
            img = render_level(level, tile_size=32)

            # Save image
            output_path = Path(f'/home/nabeel/proc-dungeon-generator/level{level_num}.png')
            img.save(output_path)
            print(f"Saved to {output_path}")
            print(f"Image size: {img.size[0]}x{img.size[1]} pixels")

            # Display info
            print(f"\nLevel {level['number']} Info:")
            print(f"  Time limit: {level['time']} seconds")
            print(f"  Chips to collect: {level['chips']}")
        else:
            print(f"Level {level_num} not found. Available levels: 1-{len(levels)}")


if __name__ == '__main__':
    main()
