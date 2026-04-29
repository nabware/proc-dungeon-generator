# Masters Supervisor Meeting Notes

## Key Pyramid materials

- Original level image: [original_key_pyramid_level.png](original_key_pyramid_level.png)
- Soft-lock variant image: [latest_soft_lock_key_pyramid.png](latest_soft_lock_key_pyramid.png)

## What changed in the soft-lock variant

- The geometry is kept the same as the original Key Pyramid level.
- Only the right-side locks were swapped so the branch structure changes.
- The goal is to create a reachable branch that cannot still complete the level.

## State-count comparison on the original Key Pyramid level

- Tile-based search: 112,928 unique states explored
- Room-segmented search with memoization: 120 unique states explored

## Total state comparison

- Tile-based total unique states to consider for the original level: 112,928
- Room-segmented total unique states with memoization: 120
- Yes, the memoized room-segmented count is the one you should treat as the total unique state count for that approach

## State-space calculation

- Positions on the map: 32 x 32 = 1,024
- Chip collectible tiles: 10, so chip subsets = 2^10 = 1,024
- Key tiles: 8, so key subsets = 2^8 = 256
- Lock tiles: 9, so opened-lock subsets = 2^9 = 512
- Boot flags tracked by the solver: 4, so boot subsets = 2^4 = 16
- Upper bound on total tile-based state combinations: 1,024 x 1,024 x 256 x 512 x 16 = 2,199,023,255,552

## What that means

- The 112,928 tile-based figure is the number of unique states the solver actually reached on this level.
- The 120 room-segmented figure is the corresponding unique reachable-state count after compression and memoization.
- The huge calculated upper bound shows why the solver needs pruning and memoization even though the real reachable set is much smaller.

## Suggested talking points

- The room-segmented approach cuts the explored state space dramatically compared with tile-level BFS.
- Memoization is the difference between a tractable universal check and a search that explodes on cycles.
- The soft-lock variant is useful because it distinguishes “there exists a winning path” from “every reachable branch can still win.”
- The original Key Pyramid is a good benchmark because it has enough branching to expose the difference clearly.

## Results worth mentioning

- Original level still solves normally under both tile-based and room-segmented approaches.
- The soft-lock variant is solvable in the normal sense, but the universal branch check fails as intended.
- That makes it a good test case for validating all possible paths, not just finding one winning path.

## Uncapped universal BFS implementation

- Script: [run_room_universal_bfs.py](../run_room_universal_bfs.py)
- This is room-segmented BFS with no artificial expansion cap.
- It checks the universal property: every reachable branch can still reach a normal win state.

### Commands

- Original Key Pyramid:
	- `source venv/bin/activate && python3 run_room_universal_bfs.py --dat "./CCUP/Level Sets/CCLP1/data/CCLP1.dat" --level 1`
- Latest soft-lock variant:
	- `source venv/bin/activate && python3 run_room_universal_bfs.py --level-json generated_key_pyramid_soft_lock.json --show-counterexample`












do the 3 ideas below relate to what we have done?

memoize all possible states

storing states in a hashtable

is checking for full-solvability co-NP-complete?

Yes, all three relate, with one correction on the complexity label.

Memoize all possible states
Related, with a nuance: you memoize all reachable states, not all theoretically possible states.
That is exactly what prevents infinite revisits/cycles and makes both forward and reverse passes tractable.
Storing states in a hashtable
Exactly what you do.
In Python terms, your state tuples are stored in hash-based structures (set/dict) for (O(1))-average membership and predecessor/successor bookkeeping.
Is full-solvability co-NP-complete?
Depends on how you formalize input size and model.
For your implemented check on an explicit explored state graph, the test is in (P): forward reachability + reverse reachability.
So for a fixed generated state graph, it is not naturally a co-NP-complete problem.
For the general puzzle family (compact level description, potentially exponential state space), complexity is typically argued in PSPACE territory rather than NP/co-NP.
So the short takeaway:

Idea 1 and 2 are exactly the engineering backbone of what you built.
Idea 3 is the right kind of question, but “co-NP-complete” is usually not the best class for the unrestricted version you are studying.