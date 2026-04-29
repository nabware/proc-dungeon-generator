% Overlay encoding: generate a valid tree but force an impossible boss-lock key.
% This keeps a model satisfiable for clingo while making the derived abstract graph
% unsolvable for our BFS validator.

#include "dungeon_generator.lp".

% Add an impossible dependency: boss lock now requires sk(99), which is never a node.
taft(sk(99), bl(1)).
