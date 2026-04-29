% Variant generator that intentionally allows a key to be placed behind its lock.
% This produces a satisfiable ASP model that our BFS validator should reject.

#const sk_count=2.
#const sl_count=2.
#const dl_count=2.
#const c_count=3.
#const p_count=2.
#const t_count=2.
#const r_count=2.
#const max_depth=25.
#const min_boss_depth=6.
#const max_start_children=4.
#const min_deep_nodes=8.

node(start; boss; di(1); bk(1); bl(1)).
node(sk(1..sk_count); sl(1..sl_count); dl(1..dl_count)).
node(c(1..c_count); p(1..p_count); t(1..t_count); r(1..r_count)).

% Generate a tree via parent assignment.
paft(start,start).
1 { paft(B, N) : paft(_, B), B != N } 1 :- node(N), N != start.

% Force the bad pattern: the key for sl(1) is physically behind sl(1).
paft(sl(1), sk(1)).

% Boss and boss key should be terminal in this prototype.
:- node(N), paft(boss, N).
:- node(N), paft(bk(1), N).

% Boss must be behind the boss lock.
:- not paft(bl(1), boss).

% Temporal dependencies for lock/key concepts.
taft(sk(I), sl(I)) :- node(sk(I)), node(sl(I)).
taft(di(1), dl(I)) :- node(dl(I)).
taft(bk(1), bl(1)).

% Reachability in physical tree.
reach(A, B) :- paft(A, B), A != B.
reach(A, C) :- reach(A, B), paft(B, C), B != C.

% Note: the normal anti-pattern constraints are intentionally omitted here.
% This lets clingo generate a graph that is structurally valid but unsolvable.

% Compute physical depth from start.
depth_value(0..max_depth).
depth(start, 0).
depth(N, D1) :- paft(P, N), P != N, depth(P, D0), depth_value(D0), D1 = D0 + 1, depth_value(D1).

% Encourage deeper, less star-like trees.
start_child(N) :- paft(start, N), N != start.
deep_node(N) :- depth(N, D), D >= 2.

% Boss should be several steps from the start.
:- depth(boss, D), D < min_boss_depth.

% Prevent start from owning most children.
:- max_start_children + 1 { start_child(N) }.

% Ensure a meaningful amount of depth-2+ structure.
:- #count { N : deep_node(N) } < min_deep_nodes.

% Avoid back-to-back lock nodes.
lock(sl(I)) :- node(sl(I)).
lock(dl(I)) :- node(dl(I)).
lock(bl(1)).
:- paft(A, B), lock(A), lock(B).

#show node/1.
#show paft/2.
#show taft/2.