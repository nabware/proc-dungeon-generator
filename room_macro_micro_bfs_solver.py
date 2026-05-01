#!/usr/bin/env python3
"""Two-graph prototype solver: macro room BFS + micro tile BFS.

This file is intentionally separate from the current production graph solver.
It demonstrates a strict hierarchical pipeline:
1) Room graph BFS to build a room sequence.
2) Tile BFS inside room transitions to execute that sequence.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path
import time

from tile_level_bfs_solver import (
    BLOCKED_IDS,
    CHIP_IDS,
    EXIT_IDS,
    FIRE_BOOTS_ID,
    FIRE_IDS,
    FLIPPERS_ID,
    FORCE_FLOOR_IDS,
    ICE_IDS,
    ICE_SKATES_ID,
    KEY_TO_INDEX,
    LOCK_TO_INDEX,
    SOCKET_IDS,
    START_IDS,
    SUCTION_BOOTS_ID,
    WATER_IDS,
    effective_tile_id,
    find_start_position,
    load_level_by_number,
    pos_to_xy,
)
from path_gif_renderer import render_route_gif
from path_icon_renderer import create_path_icon_sheet

WIDTH = 32
HEIGHT = 32
TOTAL = WIDTH * HEIGHT


def neighbors(pos: int) -> list[int]:
    x = pos % WIDTH
    y = pos // WIDTH
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


def is_static_walkable(tile_id: int) -> bool:
    return tile_id not in BLOCKED_IDS


def build_room_graph(level: dict) -> dict:
    tiles = [effective_tile_id(level, p) for p in range(TOTAL)]

    walkable = {p for p in range(TOTAL) if is_static_walkable(tiles[p])}
    lock_positions = {p for p in walkable if tiles[p] in LOCK_TO_INDEX}
    socket_positions = {p for p in walkable if tiles[p] in SOCKET_IDS}
    hazard_positions = {
        p
        for p in walkable
        if tiles[p] in WATER_IDS or tiles[p] in FIRE_IDS or tiles[p] in ICE_IDS or tiles[p] in FORCE_FLOOR_IDS
    }
    separators = lock_positions | socket_positions | hazard_positions
    room_walkable = walkable - separators

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
                "exit_positions": [],
                "start_positions": [],
            }
        )

    for room in rooms:
        for p in room["tiles"]:
            t = tiles[p]
            if t in CHIP_IDS:
                room["chip_positions"].append(p)
            if t in KEY_TO_INDEX:
                room["key_positions"].append(p)
            if t in EXIT_IDS:
                room["exit_positions"].append(p)
            if t in START_IDS:
                room["start_positions"].append(p)

    edge_map: dict[tuple[int, int], dict] = {}
    seen_sep: set[int] = set()
    for gate_start in sorted(separators):
        if gate_start in seen_sep:
            continue

        # Connected separator component (for example multi-tile water region).
        q = deque([gate_start])
        seen_sep.add(gate_start)
        component: list[int] = []
        side_rooms: set[int] = set()
        lock_colors: set[int] = set()
        socket_positions: list[int] = []

        while q:
            gate_pos = q.popleft()
            component.append(gate_pos)
            tile = tiles[gate_pos]
            if tile in LOCK_TO_INDEX:
                lock_colors.add(LOCK_TO_INDEX[tile])
            if tile in SOCKET_IDS:
                socket_positions.append(gate_pos)

            for n in neighbors(gate_pos):
                if n in separators and n not in seen_sep:
                    seen_sep.add(n)
                    q.append(n)
                rid = room_id_by_pos.get(n)
                if rid is not None:
                    side_rooms.add(rid)

        side_rooms_sorted = sorted(side_rooms)
        if len(side_rooms_sorted) < 2:
            continue

        for i in range(len(side_rooms_sorted)):
            for j in range(i + 1, len(side_rooms_sorted)):
                a = side_rooms_sorted[i]
                b = side_rooms_sorted[j]
                if a == b:
                    continue
                u, v = (a, b) if a < b else (b, a)
                key = (u, v)
                if key not in edge_map:
                    edge_map[key] = {
                        "u": u,
                        "v": v,
                        "connector_positions": [],
                        "lock_colors": set(),
                        "socket_positions": [],
                    }
                edge_map[key]["connector_positions"].extend(component)
                edge_map[key]["lock_colors"].update(lock_colors)
                edge_map[key]["socket_positions"].extend(socket_positions)

    room_edges = []
    room_adjacency: dict[int, list[dict]] = {r["id"]: [] for r in rooms}
    for _, e in sorted(edge_map.items()):
        edge = {
            "u": e["u"],
            "v": e["v"],
            "connector_positions": tuple(sorted(e["connector_positions"])),
            "lock_colors": tuple(sorted(e["lock_colors"])),
            "socket_positions": tuple(sorted(e["socket_positions"])),
        }
        room_edges.append(edge)
        room_adjacency[edge["u"]].append(edge)
        room_adjacency[edge["v"]].append(edge)

    return {
        "tiles": tiles,
        "rooms": rooms,
        "room_id_by_pos": room_id_by_pos,
        "lock_positions": lock_positions,
        "socket_positions": socket_positions,
        "hazard_positions": hazard_positions,
        "separators": separators,
        "room_edges": room_edges,
        "room_adjacency": room_adjacency,
    }


def _apply_room_collection(
    room: dict,
    chip_mask: int,
    keys: tuple[int, int, int, int],
    key_mask: int,
    has_flippers: bool,
    has_fire_boots: bool,
    has_ice_skates: bool,
    has_suction_boots: bool,
    chip_index: dict[int, int],
    key_index: dict[int, int],
    tiles: list[int],
) -> tuple[int, tuple[int, int, int, int], int, bool, bool, bool, bool]:
    nmask = chip_mask
    nkeys = list(keys)
    nkey_mask = key_mask
    nflippers = has_flippers
    nfire = has_fire_boots
    nice = has_ice_skates
    nsuction = has_suction_boots

    for p in room["chip_positions"]:
        idx = chip_index.get(p)
        if idx is not None:
            nmask |= 1 << idx

    for p in room["key_positions"]:
        idx = key_index.get(p)
        if idx is None:
            continue
        b = 1 << idx
        if nkey_mask & b:
            continue
        nkeys[KEY_TO_INDEX[tiles[p]]] += 1
        nkey_mask |= b

    for p in room["tiles"]:
        t = tiles[p]
        if t == FLIPPERS_ID:
            nflippers = True
        elif t == FIRE_BOOTS_ID:
            nfire = True
        elif t == ICE_SKATES_ID:
            nice = True
        elif t == SUCTION_BOOTS_ID:
            nsuction = True

    return nmask, tuple(nkeys), nkey_mask, nflippers, nfire, nice, nsuction


def _pick_traversable_connector(
    edge: dict,
    keys: tuple[int, int, int, int],
    opened_locks: int,
    chip_mask: int,
    chips_required: int,
    lock_bit: dict[int, int],
    tiles: list[int],
    has_flippers: bool,
    has_fire_boots: bool,
    has_ice_skates: bool,
    has_suction_boots: bool,
) -> tuple[int | None, tuple[int, int, int, int], int]:
    nkeys = list(keys)
    nopened = opened_locks

    def hazard_passable(tile: int) -> bool:
        if tile in WATER_IDS and not has_flippers:
            return False
        if tile in FIRE_IDS and not has_fire_boots:
            return False
        if tile in ICE_IDS and not has_ice_skates:
            return False
        if tile in FORCE_FLOOR_IDS and not has_suction_boots:
            return False
        return True

    for lp in edge["connector_positions"]:
        tile = tiles[lp]
        if not hazard_passable(tile):
            continue
        if tile in SOCKET_IDS and chip_mask.bit_count() < chips_required:
            continue
        if tile not in LOCK_TO_INDEX:
            return lp, tuple(nkeys), nopened
        b = lock_bit[lp]
        if nopened & (1 << b):
            return lp, tuple(nkeys), nopened

    for lp in edge["connector_positions"]:
        tile = tiles[lp]
        if not hazard_passable(tile):
            continue
        if tile in SOCKET_IDS:
            if chip_mask.bit_count() < chips_required:
                continue
            return lp, tuple(nkeys), nopened
        if tile not in LOCK_TO_INDEX:
            return lp, tuple(nkeys), nopened
        color = LOCK_TO_INDEX[tiles[lp]]
        if nkeys[color] <= 0:
            continue
        if color != 2:
            nkeys[color] -= 1
        b = lock_bit[lp]
        nopened |= 1 << b
        return lp, tuple(nkeys), nopened

    return None, keys, opened_locks


def macro_room_bfs_plan(level: dict, room_graph: dict, collect_all: bool = False) -> dict:
    tiles: list[int] = room_graph["tiles"]
    rooms: list[dict] = room_graph["rooms"]
    room_id_by_pos: dict[int, int] = room_graph["room_id_by_pos"]
    room_adjacency: dict[int, list[dict]] = room_graph["room_adjacency"]

    chips_required = int(level["chips"])
    start_pos = find_start_position(level)
    if start_pos is None:
        return {"solvable": False, "reason": "No start tile found."}

    start_room = room_id_by_pos.get(start_pos)
    if start_room is None:
        return {"solvable": False, "reason": "Start is not inside a room component."}

    chip_positions = [p for p in range(TOTAL) if tiles[p] in CHIP_IDS]
    chip_index = {p: i for i, p in enumerate(chip_positions)}
    key_positions = [p for p in range(TOTAL) if tiles[p] in KEY_TO_INDEX]
    key_index = {p: i for i, p in enumerate(key_positions)}
    lock_positions = [p for p in range(TOTAL) if tiles[p] in LOCK_TO_INDEX]
    lock_bit = {p: i for i, p in enumerate(lock_positions)}

    total_collectibles = len(set(chip_positions + key_positions))

    start_chip_mask = 0
    start_keys = (0, 0, 0, 0)
    start_key_mask = 0
    start_opened = 0
    start_flippers = False
    start_fire = False
    start_ice = False
    start_suction = False

    start_chip_mask, start_keys, start_key_mask, start_flippers, start_fire, start_ice, start_suction = _apply_room_collection(
        rooms[start_room],
        start_chip_mask,
        start_keys,
        start_key_mask,
        start_flippers,
        start_fire,
        start_ice,
        start_suction,
        chip_index,
        key_index,
        tiles,
    )

    start_state = (
        start_room,
        start_chip_mask,
        start_keys,
        start_key_mask,
        start_opened,
        start_flippers,
        start_fire,
        start_ice,
        start_suction,
    )
    q = deque([start_state])
    seen = {start_state}
    parent: dict[tuple, tuple | None] = {start_state: None}
    via_edge: dict[tuple, tuple[int, int, tuple[int, ...]] | None] = {start_state: None}

    def is_goal(state: tuple) -> bool:
        rid, chip_mask, _keys, key_mask, _opened, _flippers, _fire, _ice, _suction = state
        room = rooms[rid]
        has_exit = len(room["exit_positions"]) > 0
        if not has_exit:
            return False
        if chip_mask.bit_count() < chips_required:
            return False
        if collect_all and (chip_mask.bit_count() + key_mask.bit_count() < total_collectibles):
            return False
        return True

    goal_state = None
    while q:
        state = q.popleft()
        if is_goal(state):
            goal_state = state
            break

        rid, chip_mask, keys, key_mask, opened, has_flippers, has_fire_boots, has_ice_skates, has_suction_boots = state
        for edge in room_adjacency[rid]:
            if edge["u"] == rid:
                nr = edge["v"]
            else:
                nr = edge["u"]

            _lock_pos, nkeys, nopened = _pick_traversable_connector(
                edge,
                keys,
                opened,
                chip_mask,
                chips_required,
                lock_bit,
                tiles,
                has_flippers,
                has_fire_boots,
                has_ice_skates,
                has_suction_boots,
            )
            if _lock_pos is None:
                continue

            nmask, nkeys2, nkey_mask, nflippers, nfire, nice, nsuction = _apply_room_collection(
                rooms[nr],
                chip_mask,
                nkeys,
                key_mask,
                has_flippers,
                has_fire_boots,
                has_ice_skates,
                has_suction_boots,
                chip_index,
                key_index,
                tiles,
            )
            nstate = (nr, nmask, nkeys2, nkey_mask, nopened, nflippers, nfire, nice, nsuction)
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            via_edge[nstate] = (rid, nr, edge["connector_positions"])
            q.append(nstate)

    if goal_state is None:
        return {"solvable": False, "reason": "No macro room plan found."}

    steps_rev: list[tuple[int, int, tuple[int, ...]]] = []
    state_rev: list[tuple] = [goal_state]
    cur = goal_state
    while parent[cur] is not None:
        step = via_edge[cur]
        if step is not None:
            steps_rev.append(step)
        state_rev.append(parent[cur])
        cur = parent[cur]
    steps = list(reversed(steps_rev))
    state_history = list(reversed(state_rev))

    return {
        "solvable": True,
        "steps": steps,
        "state_history": state_history,
        "goal_state": goal_state,
        "chip_index": chip_index,
        "key_index": key_index,
        "lock_bit": lock_bit,
        "visited_states": len(seen),
    }


def validate_all_solution_paths(level: dict) -> dict:
    """Return whether every reachable branch can still reach a collect-all exit.

    The search is memoized at the room-state level so it stays tractable on the
    Key Pyramid layouts, while still exploring every distinct reachable state.
    """
    room_graph = build_room_graph(level)
    tiles: list[int] = room_graph["tiles"]
    rooms: list[dict] = room_graph["rooms"]
    room_id_by_pos: dict[int, int] = room_graph["room_id_by_pos"]
    room_adjacency: dict[int, list[dict]] = room_graph["room_adjacency"]

    chips_required = int(level["chips"])
    start_pos = find_start_position(level)
    if start_pos is None:
        return {"valid": False, "reason": "No start tile found."}

    start_room = room_id_by_pos.get(start_pos)
    if start_room is None:
        return {"valid": False, "reason": "Start is not inside a room component."}

    chip_positions = [p for p in range(TOTAL) if tiles[p] in CHIP_IDS]
    chip_index = {p: i for i, p in enumerate(chip_positions)}
    key_positions = [p for p in range(TOTAL) if tiles[p] in KEY_TO_INDEX]
    key_index = {p: i for i, p in enumerate(key_positions)}
    lock_positions = [p for p in range(TOTAL) if tiles[p] in LOCK_TO_INDEX]
    lock_bit = {p: i for i, p in enumerate(lock_positions)}
    total_collectibles = len(set(chip_positions + key_positions))

    start_chip_mask = 0
    start_keys = (0, 0, 0, 0)
    start_key_mask = 0
    start_opened = 0
    start_flippers = False
    start_fire = False
    start_ice = False
    start_suction = False

    start_chip_mask, start_keys, start_key_mask, start_flippers, start_fire, start_ice, start_suction = _apply_room_collection(
        rooms[start_room],
        start_chip_mask,
        start_keys,
        start_key_mask,
        start_flippers,
        start_fire,
        start_ice,
        start_suction,
        chip_index,
        key_index,
        tiles,
    )

    start_state = (
        start_room,
        start_chip_mask,
        start_keys,
        start_key_mask,
        start_opened,
        start_flippers,
        start_fire,
        start_ice,
        start_suction,
    )

    q = deque([start_state])
    seen = {start_state}
    parent: dict[tuple, tuple | None] = {start_state: None}
    successors: dict[tuple, list[tuple]] = {}

    expanded = 0

    while q:
        state = q.popleft()
        expanded += 1
        rid, chip_mask, keys, key_mask, opened, has_flippers, has_fire_boots, has_ice_skates, has_suction_boots = state
        room = rooms[rid]
        state_successors: list[tuple] = []

        if len(room["exit_positions"]) > 0 and chip_mask.bit_count() >= chips_required:
            collected_count = chip_mask.bit_count() + key_mask.bit_count()
            if collected_count < total_collectibles:
                state_chain_rev = [state]
                cur = state
                while parent[cur] is not None:
                    cur = parent[cur]
                    state_chain_rev.append(cur)
                state_history = list(reversed(state_chain_rev))
                return {
                    "valid": False,
                    "reason": "Found a solution that reaches the exit without collecting every chip/key.",
                    "expanded_states": expanded,
                    "total_collectibles": total_collectibles,
                    "collected_collectibles": collected_count,
                    "counterexample_state_history": state_history,
                    "counterexample_rooms": [entry[0] for entry in state_history],
                }

        for edge in room_adjacency[rid]:
            if edge["u"] == rid:
                nr = edge["v"]
            else:
                nr = edge["u"]

            _lock_pos, nkeys, nopened = _pick_traversable_connector(
                edge,
                keys,
                opened,
                chip_mask,
                chips_required,
                lock_bit,
                tiles,
                has_flippers,
                has_fire_boots,
                has_ice_skates,
                has_suction_boots,
            )
            if _lock_pos is None:
                continue

            nmask, nkeys2, nkey_mask, nflippers, nfire, nice, nsuction = _apply_room_collection(
                rooms[nr],
                chip_mask,
                nkeys,
                key_mask,
                has_flippers,
                has_fire_boots,
                has_ice_skates,
                has_suction_boots,
                chip_index,
                key_index,
                tiles,
            )
            nstate = (nr, nmask, nkeys2, nkey_mask, nopened, nflippers, nfire, nice, nsuction)
            state_successors.append(nstate)
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            q.append(nstate)

        successors[state] = state_successors

    valid_goals: set[tuple] = set()
    reverse_edges: dict[tuple, list[tuple]] = {state: [] for state in seen}
    for state, state_successors in successors.items():
        for successor in state_successors:
            reverse_edges.setdefault(successor, []).append(state)

    winning: set[tuple] = set()
    work: deque[tuple] = deque()
    for state in seen:
        rid, chip_mask, _keys, key_mask, _opened, _flippers, _fire, _ice, _suction = state
        room = rooms[rid]
        if len(room["exit_positions"]) > 0 and chip_mask.bit_count() >= chips_required:
            collected_count = chip_mask.bit_count() + key_mask.bit_count()
            if collected_count == total_collectibles:
                winning.add(state)
                work.append(state)
                valid_goals.add(state)

    while work:
        state = work.popleft()
        for prev in reverse_edges.get(state, []):
            if prev in winning:
                continue
            winning.add(prev)
            work.append(prev)

    if start_state not in winning:
        return {
            "valid": False,
            "reason": "Start state cannot reach a collect-all solution.",
            "expanded_states": expanded,
            "total_collectibles": total_collectibles,
        }

    losing_state = None
    for state in seen:
        if state not in winning:
            losing_state = state
            break

    if losing_state is not None:
        state_chain_rev = [losing_state]
        cur = losing_state
        while parent[cur] is not None:
            cur = parent[cur]
            state_chain_rev.append(cur)
        state_history = list(reversed(state_chain_rev))
        return {
            "valid": False,
            "reason": "Found a reachable state that cannot still reach a collect-all win.",
            "expanded_states": expanded,
            "total_collectibles": total_collectibles,
            "counterexample_state_history": state_history,
            "counterexample_rooms": [entry[0] for entry in state_history],
        }

    return {
        "valid": True,
        "expanded_states": expanded,
        "total_collectibles": total_collectibles,
        "state_count": len(seen),
        "winning_state_count": len(winning),
        "goal_state_count": len(valid_goals),
    }


def validate_no_softlock_to_exit(level: dict) -> dict:
    """Return whether every reachable branch can still reach the normal win goal.

    Goal condition here is the standard objective: reach an exit with enough chips.
    """
    room_graph = build_room_graph(level)
    tiles: list[int] = room_graph["tiles"]
    rooms: list[dict] = room_graph["rooms"]
    room_id_by_pos: dict[int, int] = room_graph["room_id_by_pos"]
    room_adjacency: dict[int, list[dict]] = room_graph["room_adjacency"]

    chips_required = int(level["chips"])
    start_pos = find_start_position(level)
    if start_pos is None:
        return {"valid": False, "reason": "No start tile found."}

    start_room = room_id_by_pos.get(start_pos)
    if start_room is None:
        return {"valid": False, "reason": "Start is not inside a room component."}

    chip_positions = [p for p in range(TOTAL) if tiles[p] in CHIP_IDS]
    chip_index = {p: i for i, p in enumerate(chip_positions)}
    key_positions = [p for p in range(TOTAL) if tiles[p] in KEY_TO_INDEX]
    key_index = {p: i for i, p in enumerate(key_positions)}
    lock_positions = [p for p in range(TOTAL) if tiles[p] in LOCK_TO_INDEX]
    lock_bit = {p: i for i, p in enumerate(lock_positions)}

    start_chip_mask = 0
    start_keys = (0, 0, 0, 0)
    start_key_mask = 0
    start_opened = 0
    start_flippers = False
    start_fire = False
    start_ice = False
    start_suction = False

    start_chip_mask, start_keys, start_key_mask, start_flippers, start_fire, start_ice, start_suction = _apply_room_collection(
        rooms[start_room],
        start_chip_mask,
        start_keys,
        start_key_mask,
        start_flippers,
        start_fire,
        start_ice,
        start_suction,
        chip_index,
        key_index,
        tiles,
    )

    start_state = (
        start_room,
        start_chip_mask,
        start_keys,
        start_key_mask,
        start_opened,
        start_flippers,
        start_fire,
        start_ice,
        start_suction,
    )

    q = deque([start_state])
    seen = {start_state}
    parent: dict[tuple, tuple | None] = {start_state: None}
    successors: dict[tuple, list[tuple]] = {}

    expanded = 0

    while q:
        state = q.popleft()
        expanded += 1
        rid, chip_mask, keys, key_mask, opened, has_flippers, has_fire_boots, has_ice_skates, has_suction_boots = state
        room = rooms[rid]
        state_successors: list[tuple] = []

        for edge in room_adjacency[rid]:
            if edge["u"] == rid:
                nr = edge["v"]
            else:
                nr = edge["u"]

            _lock_pos, nkeys, nopened = _pick_traversable_connector(
                edge,
                keys,
                opened,
                chip_mask,
                chips_required,
                lock_bit,
                tiles,
                has_flippers,
                has_fire_boots,
                has_ice_skates,
                has_suction_boots,
            )
            if _lock_pos is None:
                continue

            nmask, nkeys2, nkey_mask, nflippers, nfire, nice, nsuction = _apply_room_collection(
                rooms[nr],
                chip_mask,
                nkeys,
                key_mask,
                has_flippers,
                has_fire_boots,
                has_ice_skates,
                has_suction_boots,
                chip_index,
                key_index,
                tiles,
            )
            nstate = (nr, nmask, nkeys2, nkey_mask, nopened, nflippers, nfire, nice, nsuction)
            state_successors.append(nstate)
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            q.append(nstate)

        successors[state] = state_successors

    reverse_edges: dict[tuple, list[tuple]] = {state: [] for state in seen}
    for state, state_successors in successors.items():
        for successor in state_successors:
            reverse_edges.setdefault(successor, []).append(state)

    winning: set[tuple] = set()
    goal_states: set[tuple] = set()
    work: deque[tuple] = deque()
    for state in seen:
        rid, chip_mask, _keys, _key_mask, _opened, _flippers, _fire, _ice, _suction = state
        room = rooms[rid]
        if len(room["exit_positions"]) > 0 and chip_mask.bit_count() >= chips_required:
            winning.add(state)
            goal_states.add(state)
            work.append(state)

    while work:
        state = work.popleft()
        for prev in reverse_edges.get(state, []):
            if prev in winning:
                continue
            winning.add(prev)
            work.append(prev)

    if not goal_states:
        return {
            "valid": False,
            "reason": "No reachable win state exists.",
            "expanded_states": expanded,
        }

    if start_state not in winning:
        return {
            "valid": False,
            "reason": "Start state cannot reach a win state.",
            "expanded_states": expanded,
        }

    losing_state = None
    for state in seen:
        if state not in winning:
            losing_state = state
            break

    if losing_state is not None:
        state_chain_rev = [losing_state]
        cur = losing_state
        while parent[cur] is not None:
            cur = parent[cur]
            state_chain_rev.append(cur)
        state_history = list(reversed(state_chain_rev))
        return {
            "valid": False,
            "reason": "Found a reachable state that cannot still reach a win state.",
            "expanded_states": expanded,
            "counterexample_state_history": state_history,
            "counterexample_rooms": [entry[0] for entry in state_history],
            "state_count": len(seen),
            "winning_state_count": len(winning),
            "goal_state_count": len(goal_states),
        }

    return {
        "valid": True,
        "expanded_states": expanded,
        "state_count": len(seen),
        "winning_state_count": len(winning),
        "goal_state_count": len(goal_states),
    }


def _step_effects(
    pos: int,
    state: tuple,
    tiles: list[int],
    chips_required: int,
    chip_index: dict[int, int],
    key_index: dict[int, int],
    lock_bit: dict[int, int],
) -> tuple | None:
    (
        _old_pos,
        chip_mask,
        keys,
        key_mask,
        opened_locks,
        has_flippers,
        has_fire_boots,
        has_ice_skates,
        has_suction_boots,
    ) = state

    tile = tiles[pos]
    if tile in BLOCKED_IDS:
        return None
    if tile in WATER_IDS and not has_flippers:
        return None
    if tile in FIRE_IDS and not has_fire_boots:
        return None
    if tile in ICE_IDS and not has_ice_skates:
        return None
    if tile in FORCE_FLOOR_IDS and not has_suction_boots:
        return None
    if tile in SOCKET_IDS and chip_mask.bit_count() < chips_required:
        return None

    nkeys = list(keys)
    nmask = chip_mask
    nkey_mask = key_mask
    nopened = opened_locks
    nflippers = has_flippers
    nfire = has_fire_boots
    nice = has_ice_skates
    nsuction = has_suction_boots

    if tile in LOCK_TO_INDEX:
        b = lock_bit[pos]
        if not (nopened & (1 << b)):
            color = LOCK_TO_INDEX[tile]
            if nkeys[color] <= 0:
                return None
            if color != 2:
                nkeys[color] -= 1
            nopened |= 1 << b

    if pos in chip_index:
        nmask |= 1 << chip_index[pos]

    if pos in key_index:
        b = 1 << key_index[pos]
        if not (nkey_mask & b):
            nkeys[KEY_TO_INDEX[tile]] += 1
            nkey_mask |= b

    if tile == FLIPPERS_ID:
        nflippers = True
    if tile == FIRE_BOOTS_ID:
        nfire = True
    if tile == ICE_SKATES_ID:
        nice = True
    if tile == SUCTION_BOOTS_ID:
        nsuction = True

    return (
        pos,
        nmask,
        tuple(nkeys),
        nkey_mask,
        nopened,
        nflippers,
        nfire,
        nice,
        nsuction,
    )


def local_tile_bfs_to_room(
    current_state: tuple,
    current_room: int,
    target_room: int,
    connector_lock_positions: tuple[int, ...],
    room_graph: dict,
    chips_required: int,
    chip_index: dict[int, int],
    key_index: dict[int, int],
    lock_bit: dict[int, int],
) -> tuple[tuple | None, list[int] | None]:
    tiles: list[int] = room_graph["tiles"]
    room_id_by_pos: dict[int, int] = room_graph["room_id_by_pos"]
    _ = current_room
    _ = connector_lock_positions

    q = deque([current_state])
    seen = {current_state}
    parent: dict[tuple, tuple | None] = {current_state: None}

    goal_state = None
    while q:
        state = q.popleft()
        pos = state[0]

        if room_id_by_pos.get(pos) == target_room:
            goal_state = state
            break

        for npos in neighbors(pos):
            nstate = _step_effects(
                npos,
                state,
                tiles,
                chips_required,
                chip_index,
                key_index,
                lock_bit,
            )
            if nstate is None:
                continue
            if nstate in seen:
                continue

            seen.add(nstate)
            parent[nstate] = state
            q.append(nstate)

    if goal_state is None:
        return None, None, 0

    path_rev = []
    cur = goal_state
    while parent[cur] is not None:
        path_rev.append(cur[0])
        cur = parent[cur]
    path_rev.append(cur[0])
    path = list(reversed(path_rev))
    return goal_state, path, len(seen)


def local_tile_bfs_to_exit(
    current_state: tuple,
    current_room: int,
    room_graph: dict,
    chips_required: int,
    chip_index: dict[int, int],
    key_index: dict[int, int],
    lock_bit: dict[int, int],
) -> tuple[tuple | None, list[int] | None]:
    tiles: list[int] = room_graph["tiles"]
    room_id_by_pos: dict[int, int] = room_graph["room_id_by_pos"]

    q = deque([current_state])
    seen = {current_state}
    parent: dict[tuple, tuple | None] = {current_state: None}

    goal_state = None
    while q:
        state = q.popleft()
        pos = state[0]
        if room_id_by_pos.get(pos) == current_room and tiles[pos] in EXIT_IDS and state[1].bit_count() >= chips_required:
            goal_state = state
            break

        for npos in neighbors(pos):
            if room_id_by_pos.get(npos) != current_room:
                continue
            nstate = _step_effects(
                npos,
                state,
                tiles,
                chips_required,
                chip_index,
                key_index,
                lock_bit,
            )
            if nstate is None:
                continue
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            q.append(nstate)

    if goal_state is None:
        return None, None, 0

    path_rev = []
    cur = goal_state
    while parent[cur] is not None:
        path_rev.append(cur[0])
        cur = parent[cur]
    path_rev.append(cur[0])
    path = list(reversed(path_rev))
    return goal_state, path, len(seen)


def local_tile_bfs_collect_room_items(
    current_state: tuple,
    room_id: int,
    room_graph: dict,
    chips_required: int,
    chip_index: dict[int, int],
    key_index: dict[int, int],
    lock_bit: dict[int, int],
) -> tuple[tuple | None, list[int] | None]:
    tiles: list[int] = room_graph["tiles"]
    room_id_by_pos: dict[int, int] = room_graph["room_id_by_pos"]
    room = room_graph["rooms"][room_id]

    target_chip_bits = 0
    for p in room["chip_positions"]:
        idx = chip_index.get(p)
        if idx is not None:
            target_chip_bits |= 1 << idx

    target_key_bits = 0
    for p in room["key_positions"]:
        idx = key_index.get(p)
        if idx is not None:
            target_key_bits |= 1 << idx

    target_has_flippers = any(tiles[p] == FLIPPERS_ID for p in room["tiles"])
    target_has_fire_boots = any(tiles[p] == FIRE_BOOTS_ID for p in room["tiles"])
    target_has_ice_skates = any(tiles[p] == ICE_SKATES_ID for p in room["tiles"])
    target_has_suction_boots = any(tiles[p] == SUCTION_BOOTS_ID for p in room["tiles"])

    def room_cleared(state: tuple) -> bool:
        chip_mask = state[1]
        key_mask = state[3]
        has_flippers = state[5]
        has_fire_boots = state[6]
        has_ice_skates = state[7]
        has_suction_boots = state[8]
        chips_and_keys = (chip_mask & target_chip_bits) == target_chip_bits and (key_mask & target_key_bits) == target_key_bits
        boots = (
            (not target_has_flippers or has_flippers)
            and (not target_has_fire_boots or has_fire_boots)
            and (not target_has_ice_skates or has_ice_skates)
            and (not target_has_suction_boots or has_suction_boots)
        )
        return chips_and_keys and boots

    q = deque([current_state])
    seen = {current_state}
    parent: dict[tuple, tuple | None] = {current_state: None}

    goal_state = None
    while q:
        state = q.popleft()
        pos = state[0]
        if room_cleared(state):
            goal_state = state
            break

        for npos in neighbors(pos):
            if room_id_by_pos.get(npos) != room_id:
                continue
            nstate = _step_effects(
                npos,
                state,
                tiles,
                chips_required,
                chip_index,
                key_index,
                lock_bit,
            )
            if nstate is None:
                continue
            if nstate in seen:
                continue
            seen.add(nstate)
            parent[nstate] = state
            q.append(nstate)

    if goal_state is None:
        return None, None, 0

    path_rev = []
    cur = goal_state
    while parent[cur] is not None:
        path_rev.append(cur[0])
        cur = parent[cur]
    path_rev.append(cur[0])
    path = list(reversed(path_rev))
    return goal_state, path, len(seen)


def solve_two_graph_hierarchical(level: dict, collect_all: bool = False) -> dict:
    room_graph = build_room_graph(level)
    macro = macro_room_bfs_plan(level, room_graph, collect_all=collect_all)
    if not macro.get("solvable"):
        return {"solvable": False, "reason": macro.get("reason", "Macro plan failed.")}

    tiles = room_graph["tiles"]
    room_id_by_pos = room_graph["room_id_by_pos"]

    start_pos = find_start_position(level)
    if start_pos is None:
        return {"solvable": False, "reason": "No start tile found."}

    chips_required = int(level["chips"])
    chip_index = macro["chip_index"]
    key_index = macro["key_index"]
    lock_bit = macro["lock_bit"]

    # Initial dynamic state at start tile.
    start_chip_mask = 0
    if start_pos in chip_index:
        start_chip_mask |= 1 << chip_index[start_pos]

    start_keys = [0, 0, 0, 0]
    start_key_mask = 0
    if start_pos in key_index:
        start_key_mask |= 1 << key_index[start_pos]
        start_keys[KEY_TO_INDEX[tiles[start_pos]]] += 1

    start_state = (
        start_pos,
        start_chip_mask,
        tuple(start_keys),
        start_key_mask,
        0,
        tiles[start_pos] == FLIPPERS_ID,
        tiles[start_pos] == FIRE_BOOTS_ID,
        tiles[start_pos] == ICE_SKATES_ID,
        tiles[start_pos] == SUCTION_BOOTS_ID,
    )

    positions = [start_pos]
    cur_state = start_state
    micro_visited_states = 0

    for from_room, to_room, connector_lock_positions in macro["steps"]:
        cur_room = room_id_by_pos.get(cur_state[0])
        if cur_room != from_room:
            return {
                "solvable": False,
                "reason": f"Macro/micro mismatch: expected room {from_room}, got {cur_room}",
            }

        end_state, segment, visited_count = local_tile_bfs_to_room(
            cur_state,
            from_room,
            to_room,
            connector_lock_positions,
            room_graph,
            chips_required,
            chip_index,
            key_index,
            lock_bit,
        )
        if end_state is None or segment is None:
            return {
                "solvable": False,
                "reason": f"Micro BFS failed from room {from_room} to room {to_room}",
            }
        micro_visited_states += visited_count
        positions.extend(segment[1:])
        cur_state = end_state

        # Align micro execution with macro assumptions: clear room inventory on entry.
        clear_state, clear_segment, visited_count = local_tile_bfs_collect_room_items(
            cur_state,
            to_room,
            room_graph,
            chips_required,
            chip_index,
            key_index,
            lock_bit,
        )
        if clear_state is None or clear_segment is None:
            return {
                "solvable": False,
                "reason": f"Could not clear collectibles in room {to_room}",
            }
        micro_visited_states += visited_count
        positions.extend(clear_segment[1:])
        cur_state = clear_state

    # Final local BFS to reach exit in current room.
    cur_room = room_id_by_pos.get(cur_state[0])
    if cur_room is None:
        return {"solvable": False, "reason": "Current position is not inside a room."}

    end_state, segment, visited_count = local_tile_bfs_to_exit(
        cur_state,
        cur_room,
        room_graph,
        chips_required,
        chip_index,
        key_index,
        lock_bit,
    )
    if end_state is None or segment is None:
        return {"solvable": False, "reason": "Could not reach exit from final room."}
    micro_visited_states += visited_count
    positions.extend(segment[1:])

    return {
        "solvable": True,
        "moves": len(positions) - 1,
        "positions": positions,
        "macro_steps": macro["steps"],
        "macro_state_history": macro.get("state_history", []),
        "macro_goal_state": macro["goal_state"],
        "start_room": room_id_by_pos.get(start_pos),
        "rooms": len(room_graph["rooms"]),
        "room_edges": len(room_graph["room_edges"]),
        "macro_visited_states": macro.get("visited_states", 0),
        "micro_visited_states": micro_visited_states,
        "visited_states": macro.get("visited_states", 0) + micro_visited_states,
    }


def render_macro_room_sequence_png(
    level_image_path: Path,
    room_graph: dict,
    macro_steps: list[tuple[int, int, tuple[int, ...]]],
    out_path: Path,
    macro_state_history: list[tuple] | None = None,
    start_room: int | None = None,
    tile_size: int = 32,
    columns: int = 4,
) -> bool:
    """Render a PNG sheet showing the room chosen by each macro BFS step.

    Each card is a crop of the actual rendered level image, with the selected
    destination room highlighted on top of the real tile art.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except BaseException:
        return False

    level_img = Image.open(level_image_path).convert("RGBA")
    tiles = room_graph["tiles"]
    rooms = room_graph["rooms"]

    if macro_state_history is None or not macro_state_history:
        macro_state_history = []

    def room_bbox(room_id: int, pad_tiles: int = 1) -> tuple[int, int, int, int]:
        room_tiles = rooms[room_id]["tiles"]
        xs = [p % WIDTH for p in room_tiles]
        ys = [p // WIDTH for p in room_tiles]
        min_x = max(0, min(xs) - pad_tiles)
        max_x = min(WIDTH - 1, max(xs) + pad_tiles)
        min_y = max(0, min(ys) - pad_tiles)
        max_y = min(HEIGHT - 1, max(ys) + pad_tiles)
        return min_x, min_y, max_x, max_y

    def crop_room(room_id: int, state: tuple | None, accent: tuple[int, int, int, int]) -> Image.Image:
        min_x, min_y, max_x, max_y = room_bbox(room_id)
        box = (
            min_x * tile_size,
            min_y * tile_size,
            (max_x + 1) * tile_size,
            (max_y + 1) * tile_size,
        )
        crop = level_img.crop(box)
        overlay = Image.new("RGBA", crop.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        chip_mask = 0
        key_mask = 0
        opened_locks = 0
        if state is not None:
            chip_mask = state[1]
            key_mask = state[3]
            opened_locks = state[4]

        for p in rooms[room_id]["tiles"]:
            x = p % WIDTH
            y = p // WIDTH
            rx0 = (x - min_x) * tile_size
            ry0 = (y - min_y) * tile_size
            rx1 = rx0 + tile_size - 1
            ry1 = ry0 + tile_size - 1
            draw.rectangle((rx0, ry0, rx1, ry1), fill=accent)
            draw.rectangle((rx0, ry0, rx1, ry1), outline=(255, 255, 255, 80), width=1)

            tile_id = tiles[p]
            collected = False
            if tile_id in CHIP_IDS:
                collected = bool(chip_mask)
            elif tile_id in KEY_TO_INDEX:
                # This tile's item is collected if the corresponding bit is set.
                # We only know the specific tile index from the board position.
                # The bitmask key collection uses the global key-position index.
                collected = True

            # Dim tiles whose chip/key item has already been collected by this step.
            if tile_id in CHIP_IDS or tile_id in KEY_TO_INDEX:
                if state is not None:
                    # If the tile's collectible has been taken, shade it to show it is no longer present.
                    if tile_id in CHIP_IDS:
                        idx = None
                        for i, pos in enumerate([q for q in range(TOTAL) if tiles[q] in CHIP_IDS]):
                            if pos == p:
                                idx = i
                                break
                        if idx is not None and (chip_mask & (1 << idx)):
                            draw.rectangle((rx0, ry0, rx1, ry1), fill=(40, 44, 54, 135))
                    elif tile_id in KEY_TO_INDEX:
                        idx = None
                        for i, pos in enumerate([q for q in range(TOTAL) if tiles[q] in KEY_TO_INDEX]):
                            if pos == p:
                                idx = i
                                break
                        if idx is not None and (key_mask & (1 << idx)):
                            draw.rectangle((rx0, ry0, rx1, ry1), fill=(40, 44, 54, 135))

        card = Image.alpha_composite(crop, overlay)
        return card

    palette = [
        (255, 99, 71, 90),
        (255, 165, 0, 90),
        (60, 179, 113, 90),
        (30, 144, 255, 90),
        (186, 85, 211, 90),
        (255, 215, 0, 90),
    ]

    cards: list[Image.Image] = []
    font = ImageFont.load_default()

    if start_room is None and macro_steps:
        start_room = macro_steps[0][0]

    if start_room is not None:
        room = rooms[start_room]
        start_state = macro_state_history[0] if macro_state_history else None
        thumb = crop_room(start_room, start_state, (120, 120, 120, 85))
        thumb.thumbnail((220, 220), Image.Resampling.NEAREST)

        card_w = 260
        card_h = 280
        card = Image.new("RGBA", (card_w, card_h), (242, 244, 248, 255))
        draw = ImageDraw.Draw(card)
        draw.rounded_rectangle((6, 6, card_w - 6, card_h - 6), radius=14, outline=(35, 41, 57, 255), width=2)
        draw.text((14, 12), f"Start room: R{start_room}", fill=(20, 24, 32, 255), font=font)
        draw.text(
            (14, 28),
            f"chips={len(room['chip_positions'])} keys={len(room['key_positions'])} exit={len(room['exit_positions'])}",
            fill=(70, 76, 90, 255),
            font=font,
        )
        paste_x = (card_w - thumb.width) // 2
        paste_y = 60
        card.alpha_composite(thumb, (paste_x, paste_y))
        draw.rounded_rectangle((14, card_h - 34, 88, card_h - 12), radius=8, fill=(35, 41, 57, 230))
        draw.text((24, card_h - 30), "Start", fill=(255, 255, 255, 255), font=font)
        cards.append(card)

    for idx, (from_room, to_room, connector_positions) in enumerate(macro_steps, start=1):
        room = rooms[to_room]
        state = macro_state_history[idx] if idx < len(macro_state_history) else None
        visit_num = sum(1 for s in macro_state_history[: idx + 1] if s[0] == to_room) if macro_state_history else 1
        accent = palette[(idx - 1) % len(palette)]
        thumb = crop_room(to_room, state, accent)
        thumb.thumbnail((220, 220), Image.Resampling.NEAREST)

        card_w = 260
        card_h = 280
        card = Image.new("RGBA", (card_w, card_h), (245, 246, 249, 255))
        draw = ImageDraw.Draw(card)
        draw.rounded_rectangle((6, 6, card_w - 6, card_h - 6), radius=14, outline=(35, 41, 57, 255), width=2)
        draw.text((14, 12), f"Step {idx:02d}: R{from_room} -> R{to_room}", fill=(20, 24, 32, 255), font=font)
        draw.text(
            (14, 28),
            f"chips={len(room['chip_positions'])} keys={len(room['key_positions'])} exit={len(room['exit_positions'])} visit={visit_num}",
            fill=(70, 76, 90, 255),
            font=font,
        )
        draw.text((14, 42), f"connectors={list(connector_positions)}", fill=(70, 76, 90, 255), font=font)

        paste_x = (card_w - thumb.width) // 2
        paste_y = 60
        card.alpha_composite(thumb, (paste_x, paste_y))

        # Highlight the room id in the lower-left corner.
        draw.rounded_rectangle((14, card_h - 34, 88, card_h - 12), radius=8, fill=(35, 41, 57, 230))
        draw.text((24, card_h - 30), f"Room {to_room}", fill=(255, 255, 255, 255), font=font)

        cards.append(card)

    if not cards:
        return False

    rows = (len(cards) + columns - 1) // columns
    spacing = 16
    header_h = 44
    sheet_w = columns * 260 + (columns + 1) * spacing
    sheet_h = rows * 280 + (rows + 1) * spacing + header_h

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (18, 20, 26, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((spacing, 12), "Macro Room Selection List", fill=(240, 242, 247, 255), font=font)
    draw.text((spacing, 28), "Each card shows the destination room chosen by the macro BFS, using the actual room tiles.", fill=(180, 186, 200, 255), font=font)

    for idx, card in enumerate(cards):
        col = idx % columns
        row = idx // columns
        x = spacing + col * (260 + spacing)
        y = header_h + spacing + row * (280 + spacing)
        sheet.alpha_composite(card, (x, y))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out_path)
    return True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Two-graph room macro/micro BFS prototype solver")
    p.add_argument(
        "--dat",
        type=Path,
        default=Path("./CCUP/Level Sets/CCLP1/data/CCLP1.dat"),
        help="Path to DAT file.",
    )
    p.add_argument("--level", type=int, default=1, help="Level number in DAT.")
    p.add_argument("--output-prefix", type=str, default="key_pyramid_two_graph", help="Output prefix.")
    p.add_argument("--level-image", type=Path, default=None, help="Optional explicit level image path.")
    p.add_argument("--frame-ms", type=int, default=80, help="GIF frame duration.")
    p.add_argument("--collect-all", action="store_true", help="Require collecting all chips+keys before exit.")
    return p.parse_args()


def resolve_level_image_path(target_level: int, output_prefix: str, explicit_level_image: Path | None = None) -> Path:
    """Resolve background image path for path sheet/GIF rendering.

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
    return candidates[-1]


def main() -> None:
    args = parse_args()
    level = load_level_by_number(args.dat, args.level)

    t0 = time.perf_counter()
    result = solve_two_graph_hierarchical(level, collect_all=args.collect_all)
    elapsed = time.perf_counter() - t0

    print("=== Two-Graph Macro/Micro BFS ===")
    print("Solvable:", result.get("solvable"))
    print("Solve time (s):", f"{elapsed:.6f}")

    if not result.get("solvable"):
        print("Reason:", result.get("reason"))
        return

    print("Moves:", result["moves"])
    print("Rooms:", result.get("rooms"), "Room edges:", result.get("room_edges"))
    print("Macro steps:", len(result.get("macro_steps", [])))
    if result.get("macro_steps"):
        print("First 5 macro steps:", result["macro_steps"][:5])

    prefix = args.output_prefix
    level_image = resolve_level_image_path(args.level, prefix, args.level_image)

    out_sheet = Path(f"{prefix}_path_icons.png")
    out_gif = Path(f"{prefix}_route.gif")

    room_graph = build_room_graph(level)
    out_room_png = Path(f"{prefix}_macro_rooms.png")
    if render_macro_room_sequence_png(
        level_image,
        room_graph,
        result.get("macro_steps", []),
        out_room_png,
        start_room=result.get("start_room"),
    ):
        print("Macro room PNG:", out_room_png)
    else:
        print("Macro room PNG skipped: Pillow is unavailable or no macro steps.")

    if level_image.exists():
        create_path_icon_sheet(level_image, result["positions"], out_sheet, title="Two-Graph Macro/Micro BFS Path")
        render_route_gif(
            level_image,
            result["positions"],
            out_gif,
            frame_ms=max(20, args.frame_ms),
            dat_path=args.dat,
            level_number=args.level,
        )
        print("Path icon sheet:", out_sheet)
        print("Route GIF:", out_gif)
    else:
        print("Skipped renders: level image not found.")


if __name__ == "__main__":
    main()
