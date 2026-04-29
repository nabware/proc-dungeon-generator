#!/usr/bin/env python3
"""Extract and solve an exact room/corridor graph for a DAT level.

This keeps the level geometry exactly as-is and compresses straight floor corridors
into weighted graph edges. Special tiles (start/exit/chip/key/lock/socket) are
kept as explicit vertices so game mechanics are preserved.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
import heapq
from pathlib import Path
import time

from graph_solver_scratch import (
    BLOCKED_IDS,
    CHIP_IDS,
    EXIT_IDS,
    KEY_TO_INDEX,
    LOCK_TO_INDEX,
    SOCKET_IDS,
    START_IDS,
    effective_tile_id,
    find_start_position,
    load_level_by_number,
    pos_to_xy,
    solve_with_chip_state,
)
from path_gif_renderer import render_route_gif
from path_icon_renderer import create_path_icon_sheet
from room_macro_micro_bfs_solver import validate_all_solution_paths

WIDTH = 32
HEIGHT = 32
TOTAL = WIDTH * HEIGHT
LOCK_COLOR_NAMES = {0: "blue", 1: "red", 2: "green", 3: "yellow"}


def extract_room_metadata(level: dict, graph: dict) -> dict:
    """Extract room components and item inventories.

    Room boundaries are created by removing lock tiles from static walkable space.
    """
    tiles: list[int] = graph["tiles"]
    node_list: list[int] = graph["node_list"]

    walkable = {p for p in range(TOTAL) if is_static_walkable(tiles[p])}
    lock_positions = {p for p in walkable if tiles[p] in LOCK_TO_INDEX}
    room_walkable = walkable - lock_positions

    room_id_by_pos: dict[int, int] = {}
    rooms: list[dict] = []

    for start in sorted(room_walkable):
        if start in room_id_by_pos:
            continue

        rid = len(rooms)
        q = deque([start])
        room_id_by_pos[start] = rid
        room_tiles: list[int] = []

        while q:
            cur = q.popleft()
            room_tiles.append(cur)
            for n in neighbors(cur):
                if n not in room_walkable or n in room_id_by_pos:
                    continue
                room_id_by_pos[n] = rid
                q.append(n)

        rooms.append(
            {
                "id": rid,
                "tiles": sorted(room_tiles),
                "chip_positions": [],
                "key_positions": [],
                "socket_positions": [],
                "exit_positions": [],
                "start_positions": [],
                "nodes": [],
                "key_color_counts": (0, 0, 0, 0),
            }
        )

    for room in rooms:
        key_color_counts = [0, 0, 0, 0]
        for p in room["tiles"]:
            t = tiles[p]
            if t in CHIP_IDS:
                room["chip_positions"].append(p)
            if t in KEY_TO_INDEX:
                room["key_positions"].append(p)
                key_color_counts[KEY_TO_INDEX[t]] += 1
            if t in SOCKET_IDS:
                room["socket_positions"].append(p)
            if t in EXIT_IDS:
                room["exit_positions"].append(p)
            if t in START_IDS:
                room["start_positions"].append(p)
        room["key_color_counts"] = tuple(key_color_counts)

    room_id_by_node: dict[int, int | None] = {}
    for nid, pos in enumerate(node_list):
        rid = room_id_by_pos.get(pos)
        room_id_by_node[nid] = rid
        if rid is not None:
            rooms[rid]["nodes"].append(nid)

    # Build an unweighted macro room graph with lock annotations.
    # Each edge means two rooms are connected by at least one lock tile.
    room_edges_map: dict[tuple[int, int], dict] = {}
    for lp in sorted(lock_positions):
        adjacent_rooms: list[int] = []
        for n in neighbors(lp):
            rid = room_id_by_pos.get(n)
            if rid is not None and rid not in adjacent_rooms:
                adjacent_rooms.append(rid)

        if len(adjacent_rooms) < 2:
            continue

        # A lock can touch more than two room-side tiles in geometry; connect all pairs.
        for i in range(len(adjacent_rooms)):
            for j in range(i + 1, len(adjacent_rooms)):
                a = adjacent_rooms[i]
                b = adjacent_rooms[j]
                if a == b:
                    continue
                u, v = (a, b) if a < b else (b, a)
                key = (u, v)
                if key not in room_edges_map:
                    room_edges_map[key] = {
                        "u": u,
                        "v": v,
                        "has_lock": True,
                        "lock_colors": set(),
                        "lock_positions": [],
                    }
                room_edges_map[key]["lock_colors"].add(LOCK_TO_INDEX[tiles[lp]])
                room_edges_map[key]["lock_positions"].append(lp)

    room_edges: list[dict] = []
    room_edge_lookup: dict[tuple[int, int], dict] = {}
    for _k, edge in sorted(room_edges_map.items()):
        out_edge = {
            "u": edge["u"],
            "v": edge["v"],
            "has_lock": edge["has_lock"],
            "lock_colors": tuple(sorted(edge["lock_colors"])),
            "lock_positions": tuple(sorted(edge["lock_positions"])),
        }
        room_edges.append(out_edge)
        room_edge_lookup[(out_edge["u"], out_edge["v"])] = out_edge

    room_adjacency: dict[int, list[int]] = {room["id"]: [] for room in rooms}
    for edge in room_edges:
        room_adjacency[edge["u"]].append(edge["v"])
        room_adjacency[edge["v"]].append(edge["u"])
    for rid in room_adjacency:
        room_adjacency[rid] = sorted(set(room_adjacency[rid]))

    return {
        "rooms": rooms,
        "room_id_by_pos": room_id_by_pos,
        "room_id_by_node": room_id_by_node,
        "lock_positions": lock_positions,
        "room_edges": room_edges,
        "room_adjacency": room_adjacency,
        "room_edge_lookup": room_edge_lookup,
    }


def room_macro_score(node_id: int, state: tuple, graph: dict, room_meta: dict, chip_index: dict[int, int], key_index: dict[int, int]) -> tuple[int, int]:
    """Lower score is better for tie-breaking in room-priority search."""
    rid = room_meta["room_id_by_node"].get(node_id)
    if rid is None:
        return (1000, 1000)

    room = room_meta["rooms"][rid]
    _node, chip_mask, _keys, key_mask, _opened = state

    remaining_chips = 0
    for p in room["chip_positions"]:
        idx = chip_index.get(p)
        if idx is None:
            continue
        if not (chip_mask & (1 << idx)):
            remaining_chips += 1

    remaining_keys = 0
    for p in room["key_positions"]:
        idx = key_index.get(p)
        if idx is None:
            continue
        if not (key_mask & (1 << idx)):
            remaining_keys += 1

    # Prefer rooms that still contain useful collectibles.
    return (-(remaining_chips * 3 + remaining_keys * 2), len(room["nodes"]))


def is_static_walkable(tile_id: int) -> bool:
    """Static walkability used for graph extraction."""
    return tile_id not in BLOCKED_IDS


def neighbors(pos: int) -> list[int]:
    x, y = pos_to_xy(pos, WIDTH)
    out: list[int] = []
    if x > 0:
        out.append(pos - 1)
    if x < WIDTH - 1:
        out.append(pos + 1)
    if y > 0:
        out.append(pos - WIDTH)
    if y < HEIGHT - 1:
        out.append(pos + WIDTH)
    return out


def extract_compressed_graph(level: dict) -> dict:
    tiles = [effective_tile_id(level, p) for p in range(TOTAL)]
    walkable = {p for p in range(TOTAL) if is_static_walkable(tiles[p])}

    special_positions = {
        p
        for p in walkable
        if tiles[p] in START_IDS
        or tiles[p] in EXIT_IDS
        or tiles[p] in CHIP_IDS
        or tiles[p] in KEY_TO_INDEX
        or tiles[p] in LOCK_TO_INDEX
        or tiles[p] in SOCKET_IDS
    }

    degree: dict[int, int] = {}
    for p in walkable:
        d = 0
        for n in neighbors(p):
            if n in walkable:
                d += 1
        degree[p] = d

    node_positions = {p for p in walkable if degree[p] != 2 or p in special_positions}
    if not node_positions:
        raise RuntimeError("No graph nodes extracted from level.")

    node_list = sorted(node_positions)
    pos_to_node = {p: i for i, p in enumerate(node_list)}

    adjacency: dict[int, list[tuple[int, int, list[int]]]] = {i: [] for i in range(len(node_list))}
    seen_directed: set[tuple[int, int]] = set()

    for start_pos in node_list:
        start_node = pos_to_node[start_pos]
        for nxt in neighbors(start_pos):
            if nxt not in walkable:
                continue
            if (start_pos, nxt) in seen_directed:
                continue

            path = [nxt]
            prev = start_pos
            cur = nxt

            while cur not in node_positions:
                nxt_candidates = [k for k in neighbors(cur) if k in walkable and k != prev]
                if not nxt_candidates:
                    break
                if len(nxt_candidates) > 1:
                    # This should not happen for non-node degree-2 cells, but guard anyway.
                    break
                prev, cur = cur, nxt_candidates[0]
                path.append(cur)

            if cur not in pos_to_node:
                continue

            end_node = pos_to_node[cur]
            cost = 1

            adjacency[start_node].append((end_node, cost, path.copy()))
            reverse_path = list(reversed([start_pos] + path))[:-1]
            adjacency[end_node].append((start_node, cost, reverse_path))

            # Mark directed steps so we do not duplicate extraction from the same direction.
            chain = [start_pos] + path
            for i in range(len(chain) - 1):
                seen_directed.add((chain[i], chain[i + 1]))
                seen_directed.add((chain[i + 1], chain[i]))

    return {
        "tiles": tiles,
        "node_list": node_list,
        "pos_to_node": pos_to_node,
        "adjacency": adjacency,
    }


def load_level_from_json(level_json_path: Path) -> dict:
    """Load a level dictionary from a JSON file."""
    return json.loads(level_json_path.read_text())


def solve_on_compressed_graph(level: dict, graph: dict) -> dict:
    tiles: list[int] = graph["tiles"]
    node_list: list[int] = graph["node_list"]
    pos_to_node: dict[int, int] = graph["pos_to_node"]
    adjacency: dict[int, list[tuple[int, int, list[int]]]] = graph["adjacency"]

    start_pos = find_start_position(level)
    if start_pos is None:
        return {"solvable": False, "reason": "No start tile found."}
    if start_pos not in pos_to_node:
        return {"solvable": False, "reason": "Start tile was not represented in compressed graph."}

    chips_required = int(level["chips"])

    chip_positions = [p for p in range(TOTAL) if tiles[p] in CHIP_IDS]
    chip_index = {p: i for i, p in enumerate(chip_positions)}

    key_positions = [p for p in range(TOTAL) if tiles[p] in KEY_TO_INDEX]
    key_index = {p: i for i, p in enumerate(key_positions)}

    lock_positions = [p for p in range(TOTAL) if tiles[p] in LOCK_TO_INDEX]
    lock_bit = {p: i for i, p in enumerate(lock_positions)}

    start_chip_mask = 0
    if start_pos in chip_index:
        start_chip_mask |= 1 << chip_index[start_pos]

    start_keys = [0, 0, 0, 0]
    start_key_mask = 0
    if start_pos in key_index:
        start_key_mask |= 1 << key_index[start_pos]
        start_keys[KEY_TO_INDEX[tiles[start_pos]]] += 1

    start_node = pos_to_node[start_pos]
    start_state = (start_node, start_chip_mask, tuple(start_keys), start_key_mask, 0)

    q = deque([start_state])
    seen = {start_state}
    parent: dict[tuple, tuple | None] = {start_state: None}
    step_path: dict[tuple, list[int] | None] = {start_state: None}

    expanded = 0
    goal_state: tuple | None = None

    while q:
        state = q.popleft()
        expanded += 1
        node_id, chip_mask, keys, key_mask, opened_locks = state
        pos = node_list[node_id]
        tile = tiles[pos]

        if tile in EXIT_IDS and chip_mask.bit_count() >= chips_required:
            goal_state = state
            break

        for nnode, _edge_cost, path in adjacency[node_id]:
            npos = node_list[nnode]
            ntile = tiles[npos]

            # Socket is blocked until enough chips are collected.
            if ntile in SOCKET_IDS and chip_mask.bit_count() < chips_required:
                continue

            nkeys = list(keys)
            nopened = opened_locks

            # Locks consume the corresponding key on first open.
            if ntile in LOCK_TO_INDEX:
                b = lock_bit[npos]
                if not (nopened & (1 << b)):
                    color = LOCK_TO_INDEX[ntile]
                    if nkeys[color] <= 0:
                        continue
                    if color != 2:
                        nkeys[color] -= 1
                    nopened |= (1 << b)

            nchip_mask = chip_mask
            if npos in chip_index:
                nchip_mask |= 1 << chip_index[npos]

            nkey_mask = key_mask
            if npos in key_index:
                b = 1 << key_index[npos]
                if not (nkey_mask & b):
                    nkeys[KEY_TO_INDEX[ntile]] += 1
                    nkey_mask |= b

            nstate = (nnode, nchip_mask, tuple(nkeys), nkey_mask, nopened)
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            step_path[nstate] = path
            q.append(nstate)

    if goal_state is None:
        return {
            "solvable": False,
            "reason": "No path found on compressed graph.",
            "expanded_states": expanded,
        }

    positions = _reconstruct_positions_from_parents(
        start_pos,
        goal_state,
        parent,
        step_path,
        node_list,
    )

    return {
        "solvable": True,
        "moves": len(positions) - 1,
        "positions": positions,
        "expanded_states": expanded,
        "graph_nodes": len(node_list),
        "graph_edges": sum(len(v) for v in adjacency.values()) // 2,
    }


def solve_on_compressed_graph_collect_all_items(level: dict, graph: dict) -> dict:
    """Exact compressed-graph solve that collects all chips and keys before exit."""
    tiles: list[int] = graph["tiles"]
    node_list: list[int] = graph["node_list"]
    pos_to_node: dict[int, int] = graph["pos_to_node"]
    adjacency: dict[int, list[tuple[int, int, list[int]]]] = graph["adjacency"]

    start_pos = find_start_position(level)
    if start_pos is None:
        return {"solvable": False, "reason": "No start tile found."}
    if start_pos not in pos_to_node:
        return {"solvable": False, "reason": "Start tile was not represented in compressed graph."}

    chips_required = int(level["chips"])

    chip_positions = [p for p in range(TOTAL) if tiles[p] in CHIP_IDS]
    chip_index = {p: i for i, p in enumerate(chip_positions)}

    key_positions = [p for p in range(TOTAL) if tiles[p] in KEY_TO_INDEX]
    key_index = {p: i for i, p in enumerate(key_positions)}

    lock_positions = [p for p in range(TOTAL) if tiles[p] in LOCK_TO_INDEX]
    lock_bit = {p: i for i, p in enumerate(lock_positions)}

    collectible_positions = sorted(set(chip_positions + key_positions))
    collectible_index = {p: i for i, p in enumerate(collectible_positions)}
    full_collectible_mask = (1 << len(collectible_positions)) - 1 if collectible_positions else 0

    start_chip_mask = 0
    if start_pos in chip_index:
        start_chip_mask |= 1 << chip_index[start_pos]

    start_keys = [0, 0, 0, 0]
    start_key_mask = 0
    if start_pos in key_index:
        start_key_mask |= 1 << key_index[start_pos]
        start_keys[KEY_TO_INDEX[tiles[start_pos]]] += 1

    start_collectible_mask = 0
    if start_pos in collectible_index:
        start_collectible_mask |= 1 << collectible_index[start_pos]

    start_node = pos_to_node[start_pos]
    start_state = (
        start_node,
        start_chip_mask,
        tuple(start_keys),
        start_key_mask,
        0,
        start_collectible_mask,
    )

    q = deque([start_state])
    seen = {start_state}
    parent: dict[tuple, tuple | None] = {start_state: None}
    step_path: dict[tuple, list[int] | None] = {start_state: None}

    expanded = 0
    goal_state: tuple | None = None

    while q:
        state = q.popleft()
        expanded += 1
        node_id, chip_mask, keys, key_mask, opened_locks, collectible_mask = state
        pos = node_list[node_id]
        tile = tiles[pos]

        if (
            tile in EXIT_IDS
            and chip_mask.bit_count() >= chips_required
            and collectible_mask == full_collectible_mask
        ):
            goal_state = state
            break

        for nnode, _edge_cost, path in adjacency[node_id]:
            npos = node_list[nnode]
            ntile = tiles[npos]

            if ntile in SOCKET_IDS and chip_mask.bit_count() < chips_required:
                continue

            nkeys = list(keys)
            nopened = opened_locks

            if ntile in LOCK_TO_INDEX:
                b = lock_bit[npos]
                if not (nopened & (1 << b)):
                    color = LOCK_TO_INDEX[ntile]
                    if nkeys[color] <= 0:
                        continue
                    if color != 2:
                        nkeys[color] -= 1
                    nopened |= (1 << b)

            nchip_mask = chip_mask
            if npos in chip_index:
                nchip_mask |= 1 << chip_index[npos]

            nkey_mask = key_mask
            if npos in key_index:
                b = 1 << key_index[npos]
                if not (nkey_mask & b):
                    nkeys[KEY_TO_INDEX[ntile]] += 1
                    nkey_mask |= b

            ncollectible_mask = collectible_mask
            if npos in collectible_index:
                ncollectible_mask |= 1 << collectible_index[npos]

            nstate = (nnode, nchip_mask, tuple(nkeys), nkey_mask, nopened, ncollectible_mask)
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            step_path[nstate] = path
            q.append(nstate)

    if goal_state is None:
        return {
            "solvable": False,
            "reason": "No path found on collect-all-items compressed graph.",
            "expanded_states": expanded,
        }

    positions = _reconstruct_positions_from_parents(
        start_pos,
        goal_state,
        parent,
        step_path,
        node_list,
    )

    return {
        "solvable": True,
        "moves": len(positions) - 1,
        "positions": positions,
        "expanded_states": expanded,
        "collected_collectibles": goal_state[5].bit_count(),
        "total_collectibles": len(collectible_positions),
        "graph_nodes": len(node_list),
        "graph_edges": sum(len(v) for v in adjacency.values()) // 2,
    }


def solve_on_compressed_graph_room_priority(level: dict, graph: dict, room_meta: dict) -> dict:
    """Room-aware compressed graph solver.

    Uses identical game-state transitions, but prioritizes expansions toward rooms
    that still contain uncollected keys/chips and prefers same-room moves first.
    """
    tiles: list[int] = graph["tiles"]
    node_list: list[int] = graph["node_list"]
    pos_to_node: dict[int, int] = graph["pos_to_node"]
    adjacency: dict[int, list[tuple[int, int, list[int]]]] = graph["adjacency"]

    start_pos = find_start_position(level)
    if start_pos is None:
        return {"solvable": False, "reason": "No start tile found."}
    if start_pos not in pos_to_node:
        return {"solvable": False, "reason": "Start tile was not represented in compressed graph."}

    chips_required = int(level["chips"])

    chip_positions = [p for p in range(TOTAL) if tiles[p] in CHIP_IDS]
    chip_index = {p: i for i, p in enumerate(chip_positions)}

    key_positions = [p for p in range(TOTAL) if tiles[p] in KEY_TO_INDEX]
    key_index = {p: i for i, p in enumerate(key_positions)}

    lock_positions = [p for p in range(TOTAL) if tiles[p] in LOCK_TO_INDEX]
    lock_bit = {p: i for i, p in enumerate(lock_positions)}

    start_chip_mask = 0
    if start_pos in chip_index:
        start_chip_mask |= 1 << chip_index[start_pos]

    start_keys = [0, 0, 0, 0]
    start_key_mask = 0
    if start_pos in key_index:
        start_key_mask |= 1 << key_index[start_pos]
        start_keys[KEY_TO_INDEX[tiles[start_pos]]] += 1

    start_node = pos_to_node[start_pos]
    start_state = (start_node, start_chip_mask, tuple(start_keys), start_key_mask, 0)

    start_macro = room_macro_score(start_node, start_state, graph, room_meta, chip_index, key_index)
    q = deque([start_state])
    seen = {start_state}

    parent: dict[tuple, tuple | None] = {start_state: None}
    step_path: dict[tuple, list[int] | None] = {start_state: None}

    expanded = 0
    goal_state: tuple | None = None

    while q:
        state = q.popleft()
        expanded += 1
        node_id, chip_mask, keys, key_mask, opened_locks = state
        pos = node_list[node_id]
        tile = tiles[pos]

        if tile in EXIT_IDS and chip_mask.bit_count() >= chips_required:
            goal_state = state
            break

        curr_room = room_meta["room_id_by_node"].get(node_id)
        ordered_neighbors = sorted(
            adjacency[node_id],
            key=lambda edge: (
                0 if room_meta["room_id_by_node"].get(edge[0]) == curr_room else 1,
                edge[1],
            ),
        )

        for nnode, _edge_cost, path in ordered_neighbors:
            npos = node_list[nnode]
            ntile = tiles[npos]

            if ntile in SOCKET_IDS and chip_mask.bit_count() < chips_required:
                continue

            nkeys = list(keys)
            nopened = opened_locks

            if ntile in LOCK_TO_INDEX:
                b = lock_bit[npos]
                if not (nopened & (1 << b)):
                    color = LOCK_TO_INDEX[ntile]
                    if nkeys[color] <= 0:
                        continue
                    if color != 2:
                        nkeys[color] -= 1
                    nopened |= (1 << b)

            nchip_mask = chip_mask
            if npos in chip_index:
                nchip_mask |= 1 << chip_index[npos]

            nkey_mask = key_mask
            if npos in key_index:
                b = 1 << key_index[npos]
                if not (nkey_mask & b):
                    nkeys[KEY_TO_INDEX[ntile]] += 1
                    nkey_mask |= b

            nstate = (nnode, nchip_mask, tuple(nkeys), nkey_mask, nopened)
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            step_path[nstate] = path
            q.append(nstate)

    if goal_state is None:
        return {
            "solvable": False,
            "reason": "No path found on room-priority compressed graph.",
            "expanded_states": expanded,
        }

    positions = _reconstruct_positions_from_parents(
        start_pos,
        goal_state,
        parent,
        step_path,
        node_list,
    )

    return {
        "solvable": True,
        "moves": len(positions) - 1,
        "positions": positions,
        "expanded_states": expanded,
        "graph_nodes": len(node_list),
        "graph_edges": sum(len(v) for v in adjacency.values()) // 2,
    }


def _reconstruct_positions_from_parents(
    start_pos: int,
    end_state: tuple,
    parent: dict,
    step_path: dict,
    node_list: list[int],
) -> list[int]:
    """Rebuild full tile path by replaying state transitions in forward order."""
    state_chain_rev = [end_state]
    cur = end_state
    while parent[cur] is not None:
        cur = parent[cur]
        state_chain_rev.append(cur)

    state_chain = list(reversed(state_chain_rev))
    positions = [start_pos]
    for state in state_chain[1:]:
        seg = step_path.get(state)
        if seg is not None:
            for p in seg:
                if positions[-1] != p:
                    positions.append(p)
        node_pos = node_list[state[0]]
        if positions[-1] != node_pos:
            positions.append(node_pos)
    return positions


def _reconstruct_segment_positions(start_pos: int, end_state: tuple, parent: dict, step_path: dict, node_list: list[int]) -> list[int]:
    return _reconstruct_positions_from_parents(start_pos, end_state, parent, step_path, node_list)


def _run_segment_dijkstra(
    graph: dict,
    room_meta: dict,
    start_state: tuple,
    chips_required: int,
    chip_index: dict[int, int],
    key_index: dict[int, int],
    lock_bit: dict[int, int],
    stop_fn,
    max_expanded: int = 200000,
) -> tuple[tuple | None, dict, dict, int]:
    tiles: list[int] = graph["tiles"]
    node_list: list[int] = graph["node_list"]
    adjacency: dict[int, list[tuple[int, int, list[int]]]] = graph["adjacency"]

    q = deque([start_state])
    seen = {start_state}
    parent: dict[tuple, tuple | None] = {start_state: None}
    step_path: dict[tuple, list[int] | None] = {start_state: None}

    expanded = 0
    while q and expanded < max_expanded:
        state = q.popleft()
        expanded += 1
        node_id, chip_mask, keys, key_mask, opened_locks = state
        pos = node_list[node_id]
        tile = tiles[pos]

        if stop_fn(state, node_id, pos, tile):
            return state, parent, step_path, expanded

        for nnode, _edge_cost, path in adjacency[node_id]:
            npos = node_list[nnode]
            ntile = tiles[npos]

            if ntile in SOCKET_IDS and chip_mask.bit_count() < chips_required:
                continue

            nkeys = list(keys)
            nopened = opened_locks

            if ntile in LOCK_TO_INDEX:
                b = lock_bit[npos]
                if not (nopened & (1 << b)):
                    color = LOCK_TO_INDEX[ntile]
                    if nkeys[color] <= 0:
                        continue
                    if color != 2:
                        nkeys[color] -= 1
                    nopened |= (1 << b)

            nchip_mask = chip_mask
            if npos in chip_index:
                nchip_mask |= 1 << chip_index[npos]

            nkey_mask = key_mask
            if npos in key_index:
                b = 1 << key_index[npos]
                if not (nkey_mask & b):
                    nkeys[KEY_TO_INDEX[ntile]] += 1
                    nkey_mask |= b

            nstate = (nnode, nchip_mask, tuple(nkeys), nkey_mask, nopened)
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            step_path[nstate] = path
            q.append(nstate)

    return None, parent, step_path, expanded


def _run_room_clear_dijkstra(
    graph: dict,
    room_meta: dict,
    start_state: tuple,
    target_room: int,
    room_item_positions: list[int],
    chips_required: int,
    chip_index: dict[int, int],
    key_index: dict[int, int],
    lock_bit: dict[int, int],
    stop_fn,
    max_expanded: int = 200000,
) -> tuple[tuple | None, dict, dict, int]:
    """Exact micro-search that tracks item collection within a specific room via a room-local bitmask.

    The room-local mask plays the same role as chip_mask in the original solver: once all bits
    are set, the room is considered cleared.
    """
    tiles: list[int] = graph["tiles"]
    node_list: list[int] = graph["node_list"]
    adjacency: dict[int, list[tuple[int, int, list[int]]]] = graph["adjacency"]

    room_item_index = {p: i for i, p in enumerate(room_item_positions)}
    full_room_mask = (1 << len(room_item_positions)) - 1 if room_item_positions else 0

    node_id, chip_mask, keys, key_mask, opened_locks = start_state
    start_room_mask = 0
    start_pos = node_list[node_id]
    if start_pos in room_item_index:
        start_room_mask |= 1 << room_item_index[start_pos]

    start_state_ext = (node_id, chip_mask, keys, key_mask, opened_locks, start_room_mask)
    q = deque([start_state_ext])
    seen = {start_state_ext}
    parent: dict[tuple, tuple | None] = {start_state_ext: None}
    step_path: dict[tuple, list[int] | None] = {start_state_ext: None}

    expanded = 0
    while q and expanded < max_expanded:
        state = q.popleft()
        expanded += 1
        node_id, chip_mask, keys, key_mask, opened_locks, room_mask = state
        pos = node_list[node_id]
        tile = tiles[pos]

        if stop_fn(state, node_id, pos, tile, room_mask, full_room_mask):
            return state, parent, step_path, expanded

        for nnode, _edge_cost, path in adjacency[node_id]:
            npos = node_list[nnode]
            ntile = tiles[npos]

            if ntile in SOCKET_IDS and chip_mask.bit_count() < chips_required:
                continue

            nkeys = list(keys)
            nopened = opened_locks
            nroom_mask = room_mask

            if ntile in LOCK_TO_INDEX:
                b = lock_bit[npos]
                if not (nopened & (1 << b)):
                    color = LOCK_TO_INDEX[ntile]
                    if nkeys[color] <= 0:
                        continue
                    if color != 2:
                        nkeys[color] -= 1
                    nopened |= (1 << b)

            nchip_mask = chip_mask
            if npos in chip_index:
                nchip_mask |= 1 << chip_index[npos]

            nkey_mask = key_mask
            if npos in key_index:
                b = 1 << key_index[npos]
                if not (nkey_mask & b):
                    nkeys[KEY_TO_INDEX[ntile]] += 1
                    nkey_mask |= b

            if npos in room_item_index:
                nroom_mask |= 1 << room_item_index[npos]

            nstate = (nnode, nchip_mask, tuple(nkeys), nkey_mask, nopened, nroom_mask)
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            step_path[nstate] = path
            q.append(nstate)

    return None, parent, step_path, expanded


def _choose_macro_target_room(state: tuple, graph: dict, room_meta: dict, chip_index: dict[int, int], key_index: dict[int, int], chips_required: int) -> int | None:
    tiles: list[int] = graph["tiles"]
    node_list: list[int] = graph["node_list"]

    node_id, chip_mask, _keys, key_mask, _opened = state
    current_room = room_meta["room_id_by_node"].get(node_id)
    chips_done = chip_mask.bit_count() >= chips_required

    best_room = None
    best_score = -1
    for room in room_meta["rooms"]:
        rid = room["id"]
        remaining_chips = 0
        for p in room["chip_positions"]:
            idx = chip_index.get(p)
            if idx is not None and not (chip_mask & (1 << idx)):
                remaining_chips += 1

        remaining_keys = 0
        for p in room["key_positions"]:
            idx = key_index.get(p)
            if idx is not None and not (key_mask & (1 << idx)):
                remaining_keys += 1

        has_exit = any(tiles[p] in EXIT_IDS for p in room["exit_positions"])
        score = remaining_chips * 6 + remaining_keys * 3
        if has_exit and chips_done:
            score += 1000

        # Nudge the planner toward changing rooms unless current room still has value.
        if current_room is not None and rid == current_room and score == 0:
            score = -1

        if score > best_score:
            best_score = score
            best_room = rid

    if best_score <= 0:
        return None
    return best_room


def _room_items_collected(
    room: dict,
    chip_mask: int,
    key_mask: int,
    chip_index: dict[int, int],
    key_index: dict[int, int],
) -> bool:
    """Return True when every chip/key collectible in the room has been gathered."""
    for p in room["chip_positions"]:
        idx = chip_index.get(p)
        if idx is not None and not (chip_mask & (1 << idx)):
            return False

    for p in room["key_positions"]:
        idx = key_index.get(p)
        if idx is not None and not (key_mask & (1 << idx)):
            return False

    return True


def _edge_traversable_for_macro(edge: dict, keys: tuple[int, int, int, int], opened_locks: int, lock_bit: dict[int, int]) -> bool:
    # If any lock tile on this connector was already opened, traversal is free.
    for lp in edge["lock_positions"]:
        b = lock_bit.get(lp)
        if b is not None and (opened_locks & (1 << b)):
            return True

    # Otherwise require an available key for each lock color type on connector.
    # Macro BFS is room-level guidance; micro search applies exact consumption.
    for c in edge["lock_colors"]:
        if keys[c] <= 0:
            return False
    return True


def _macro_bfs_distances(current_room: int, keys: tuple[int, int, int, int], opened_locks: int, room_meta: dict, lock_bit: dict[int, int]) -> dict[int, int]:
    room_adjacency: dict[int, list[int]] = room_meta["room_adjacency"]
    room_edge_lookup: dict[tuple[int, int], dict] = room_meta["room_edge_lookup"]

    dist: dict[int, int] = {current_room: 0}
    q = deque([current_room])
    while q:
        r = q.popleft()
        for nr in room_adjacency.get(r, []):
            key = (r, nr) if r < nr else (nr, r)
            edge = room_edge_lookup.get(key)
            if edge is None:
                continue
            if not _edge_traversable_for_macro(edge, keys, opened_locks, lock_bit):
                continue
            if nr in dist:
                continue
            dist[nr] = dist[r] + 1
            q.append(nr)
    return dist


def _choose_macro_target_room_bfs(state: tuple, graph: dict, room_meta: dict, chip_index: dict[int, int], key_index: dict[int, int], chips_required: int, lock_bit: dict[int, int]) -> int | None:
    tiles: list[int] = graph["tiles"]
    node_list: list[int] = graph["node_list"]

    node_id, chip_mask, keys, key_mask, opened_locks = state
    current_room = room_meta["room_id_by_node"].get(node_id)
    if current_room is None:
        return None

    dists = _macro_bfs_distances(current_room, keys, opened_locks, room_meta, lock_bit)
    chips_done = chip_mask.bit_count() >= chips_required

    current_room_obj = room_meta["rooms"][current_room]
    current_room_has_items = not _room_items_collected(current_room_obj, chip_mask, key_mask, chip_index, key_index)

    # If we are already in a room with collectible items, keep clearing it before moving on.
    if current_room_has_items:
        return current_room

    best_room = None
    best_rank = None
    for room in room_meta["rooms"]:
        rid = room["id"]
        if rid not in dists:
            continue

        remaining_chips = 0
        for p in room["chip_positions"]:
            idx = chip_index.get(p)
            if idx is not None and not (chip_mask & (1 << idx)):
                remaining_chips += 1

        remaining_keys = 0
        for p in room["key_positions"]:
            idx = key_index.get(p)
            if idx is not None and not (key_mask & (1 << idx)):
                remaining_keys += 1

        has_exit = any(tiles[p] in EXIT_IDS for p in room["exit_positions"])
        is_goal_candidate = 1 if has_exit and chips_done else 0
        utility = remaining_chips * 6 + remaining_keys * 3 + is_goal_candidate * 1000

        if utility <= 0:
            continue

        # Prefer shorter macro distance first, then higher utility.
        rank = (dists[rid], -utility, rid)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best_room = rid

    return best_room


def solve_on_hierarchical_room_targets(level: dict, graph: dict, room_meta: dict) -> dict:
    """Two-level planner: choose a target room, then solve exact state search to it.

    Macro layer: room choice based on remaining chips/keys and exit readiness.
    Micro layer: exact Dijkstra on compressed graph with full key/lock/chip state.
    """
    tiles: list[int] = graph["tiles"]
    node_list: list[int] = graph["node_list"]
    pos_to_node: dict[int, int] = graph["pos_to_node"]

    start_pos = find_start_position(level)
    if start_pos is None:
        return {"solvable": False, "reason": "No start tile found."}
    if start_pos not in pos_to_node:
        return {"solvable": False, "reason": "Start tile was not represented in compressed graph."}

    chips_required = int(level["chips"])
    chip_positions = [p for p in range(TOTAL) if tiles[p] in CHIP_IDS]
    chip_index = {p: i for i, p in enumerate(chip_positions)}
    key_positions = [p for p in range(TOTAL) if tiles[p] in KEY_TO_INDEX]
    key_index = {p: i for i, p in enumerate(key_positions)}
    lock_positions = [p for p in range(TOTAL) if tiles[p] in LOCK_TO_INDEX]
    lock_bit = {p: i for i, p in enumerate(lock_positions)}
    start_chip_mask = 0
    if start_pos in chip_index:
        start_chip_mask |= 1 << chip_index[start_pos]
    start_keys = [0, 0, 0, 0]
    start_key_mask = 0
    if start_pos in key_index:
        start_key_mask |= 1 << key_index[start_pos]
        start_keys[KEY_TO_INDEX[tiles[start_pos]]] += 1

    cur_state = (pos_to_node[start_pos], start_chip_mask, tuple(start_keys), start_key_mask, 0)
    full_positions = [start_pos]
    expanded_total = 0

    seen_macro_states: set[tuple[int, int, tuple[int, int, int, int], int, int]] = set()
    for _ in range(64):
        node_id, chip_mask, keys, key_mask, opened_locks = cur_state
        pos = node_list[node_id]
        tile = tiles[pos]
        if tile in EXIT_IDS and chip_mask.bit_count() >= chips_required:
            return {
                "solvable": True,
                "moves": len(full_positions) - 1,
                "positions": full_positions,
                "expanded_states": expanded_total,
                "graph_nodes": len(node_list),
                "graph_edges": sum(len(v) for v in graph["adjacency"].values()) // 2,
            }

        # Include key counts in the macro signature. key_mask alone only records
        # which key tiles were collected, not how many keys remain after doors.
        macro_key = (node_id, chip_mask, keys, key_mask, opened_locks)
        if macro_key in seen_macro_states:
            break
        seen_macro_states.add(macro_key)

        target_room = _choose_macro_target_room_bfs(
            cur_state,
            graph,
            room_meta,
            chip_index,
            key_index,
            chips_required,
            lock_bit,
        )

        base_chip_mask = chip_mask
        base_key_mask = key_mask
        base_opened = opened_locks
        base_room = room_meta["room_id_by_node"].get(node_id)

        if target_room is None:
            def stop_fn(state, _nid, _pos, tile_id):
                return tile_id in EXIT_IDS and state[1].bit_count() >= chips_required
            end_state, parent, step_path, expanded = _run_segment_dijkstra(
                graph,
                room_meta,
                cur_state,
                chips_required,
                chip_index,
                key_index,
                lock_bit,
                stop_fn,
            )
        else:
            target_room_obj = room_meta["rooms"][target_room]
            room_item_positions = list(target_room_obj["chip_positions"]) + list(target_room_obj["key_positions"])

            def stop_fn(state, _nid, _pos, _tile_id, room_mask, full_room_mask):
                return room_mask == full_room_mask

            end_state, parent, step_path, expanded = _run_room_clear_dijkstra(
                graph,
                room_meta,
                cur_state,
                target_room,
                room_item_positions,
                chips_required,
                chip_index,
                key_index,
                lock_bit,
                stop_fn,
            )
        expanded_total += expanded

        if end_state is None:
            break

        segment = _reconstruct_segment_positions(node_list[cur_state[0]], end_state, parent, step_path, node_list)
        if len(segment) > 1:
            full_positions.extend(segment[1:])
        cur_state = end_state[:5]

    # Fallback to complete exact solve if macro staging stalls.
    fallback = solve_on_compressed_graph(level, graph)
    if fallback.get("solvable"):
        return {
            "solvable": True,
            "moves": fallback["moves"],
            "positions": fallback["positions"],
            "expanded_states": expanded_total + fallback.get("expanded_states", 0),
            "graph_nodes": fallback.get("graph_nodes"),
            "graph_edges": fallback.get("graph_edges"),
            "fallback_used": True,
        }

    return {
        "solvable": False,
        "reason": "No path found in hierarchical room-target planner.",
        "expanded_states": expanded_total,
    }


def benchmark(level: dict, graph: dict, repeats: int) -> dict:
    tile_times: list[float] = []
    graph_times: list[float] = []

    tile_result = None
    graph_result = None

    for _ in range(repeats):
        t0 = time.perf_counter()
        tile_result = solve_with_chip_state(level)
        tile_times.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        graph_result = solve_on_compressed_graph(level, graph)
        graph_times.append(time.perf_counter() - t0)

    assert tile_result is not None
    assert graph_result is not None

    return {
        "tile_result": tile_result,
        "graph_result": graph_result,
        "tile_min": min(tile_times),
        "tile_avg": sum(tile_times) / len(tile_times),
        "graph_min": min(graph_times),
        "graph_avg": sum(graph_times) / len(graph_times),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Exact Key Pyramid graph extraction + benchmark solver")
    p.add_argument(
        "--dat",
        type=Path,
        default=Path("./CCUP/Level Sets/CCLP1/data/CCLP1.dat"),
        help="Path to DAT file.",
    )
    p.add_argument(
        "--level-json",
        type=Path,
        default=None,
        help="Optional JSON level file to validate instead of loading from DAT.",
    )
    p.add_argument("--level", type=int, default=1, help="Level number in DAT.")
    p.add_argument("--output-prefix", type=str, default="key_pyramid_exact_graph", help="Output prefix.")
    p.add_argument("--frame-ms", type=int, default=80, help="GIF frame duration.")
    p.add_argument("--repeats", type=int, default=5, help="Benchmark repeats.")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.level_json is not None:
        level = load_level_from_json(args.level_json)
    else:
        level = load_level_by_number(args.dat, args.level)
    graph = extract_compressed_graph(level)
    room_meta = extract_room_metadata(level, graph)

    bench = benchmark(level, graph, max(1, args.repeats))
    tile_result = bench["tile_result"]
    graph_result = bench["graph_result"]
    collect_all_result = solve_on_compressed_graph_collect_all_items(level, graph)
    universal_result = validate_all_solution_paths(level)

    if not graph_result.get("solvable"):
        raise SystemExit(f"Graph solver failed: {graph_result.get('reason')}")
    if not collect_all_result.get("solvable"):
        raise SystemExit(f"Collect-all-items solver failed: {collect_all_result.get('reason')}")
    if not universal_result.get("valid"):
        raise SystemExit(f"Universal solution validation failed: {universal_result.get('reason')}")

    prefix = args.output_prefix
    level_image = Path(f"{prefix}_level.png")
    out_sheet = Path(f"{prefix}_path_icons_scratch.png")
    out_gif = Path(f"{prefix}_route_scratch.gif")

    # Reuse existing rendered Key Pyramid image if present.
    if args.level_json is not None:
        json_level_image = args.level_json.with_suffix(".png")
        if json_level_image.exists():
            level_image = json_level_image
    else:
        default_kp_image = Path("key_pyramid_level.png")
        if default_kp_image.exists():
            level_image = default_kp_image

    create_path_icon_sheet(level_image, collect_all_result["positions"], out_sheet, title="Key Pyramid Collect-All Path (step order)")
    render_route_gif(
        level_image,
        collect_all_result["positions"],
        out_gif,
        frame_ms=max(20, args.frame_ms),
        dat_path=args.dat,
        level_number=args.level,
    )

    print("=== Exact Graph Extraction ===")
    print(f"Graph nodes: {graph_result['graph_nodes']}")
    print(f"Graph edges: {graph_result['graph_edges']}")
    print(f"Rooms extracted: {len(room_meta['rooms'])}")

    print("\n=== Room Inventory Summary ===")
    for room in room_meta["rooms"]:
        print(
            f"Room {room['id']}: "
            f"nodes={len(room['nodes'])}, "
            f"chips={len(room['chip_positions'])}, "
            f"keys(R,G,B,Y)={room['key_color_counts']}, "
            f"sockets={len(room['socket_positions'])}, "
            f"exit={len(room['exit_positions'])}, "
            f"start={len(room['start_positions'])}"
        )

    print("\n=== Macro Room Graph (Unweighted) ===")
    print(f"Macro nodes (rooms): {len(room_meta['rooms'])}")
    print(f"Macro edges: {len(room_meta['room_edges'])}")
    for edge in room_meta["room_edges"]:
        colors = [LOCK_COLOR_NAMES.get(c, str(c)) for c in edge["lock_colors"]]
        print(
            f"Room {edge['u']} <-> Room {edge['v']}: "
            f"has_lock={edge['has_lock']} colors={colors}"
        )

    print("\n=== Solve Comparison ===")
    print(f"Tile solver moves: {tile_result['moves']}")
    print(f"Graph solver moves: {graph_result['moves']}")
    print(f"Collect-all-items moves: {collect_all_result['moves']}")
    print(f"Universal validation: {universal_result['valid']} ({universal_result.get('reason', 'ok')})")
    print(f"Tile solver avg s ({args.repeats}): {bench['tile_avg']:.6f}")
    print(f"Graph solver avg s ({args.repeats}): {bench['graph_avg']:.6f}")
    if bench["graph_avg"] > 0:
        print(f"Speedup (tile/graph): {bench['tile_avg'] / bench['graph_avg']:.2f}x")

    print("\n=== Outputs ===")
    print(f"Path icon sheet: {out_sheet}")
    print(f"Route GIF: {out_gif}")


if __name__ == "__main__":
    main()
