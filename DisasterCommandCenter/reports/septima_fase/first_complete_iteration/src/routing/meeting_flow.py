"""Shared reverse shortest-path guides; A* remains the fallback route solver.

Only static outdoor topology is precomputed. A snapshot is keyed by EXACT
blocked cells and EXACT costs, not an approximate risk bin. SciPy's compiled
multi-source Dijkstra amortizes one area guide across a batch of students.
Every produced path still passes temporal validation and the route gateway.
"""
from __future__ import annotations

from collections import deque
import hashlib
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra


class MeetingFlowField:
    def __init__(self, graph):
        self.graph = graph
        self.width, self.height = graph.width, graph.height
        valid = np.asarray(graph._static_valid, dtype=bool)
        self.ids = np.full(valid.shape, -1, dtype=np.int32)
        self.ys, self.xs = np.nonzero(valid)
        self.ids[self.ys, self.xs] = np.arange(len(self.xs))
        origins, targets = [], []
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            nx, ny = self.xs+dx, self.ys+dy
            inside = (nx >= 0)&(nx < self.width)&(ny >= 0)&(ny < self.height)
            source = np.flatnonzero(inside)
            dest = self.ids[ny[inside], nx[inside]]
            mask = dest >= 0
            origins.append(source[mask]); targets.append(dest[mask])
        self.origins, self.targets = np.concatenate(origins), np.concatenate(targets)
        self.signature = None
        self.fields = {}
        self.hits = self.misses = self.usage = self.rebuilds = 0
        self.cache_enabled = True
        self.maximum_fields = 8

    def prepare(self, costs, blocked):
        array = np.asarray(costs, dtype=np.float64)
        mask = np.zeros(self.ids.shape, dtype=bool)
        if blocked:
            bx, by = zip(*blocked); mask[by, bx] = True
        signature = hashlib.blake2b(array.tobytes()+mask.tobytes(), digest_size=16).digest()
        if signature == self.signature:
            return
        self.signature = signature
        self.fields.clear()
        flat_costs = 1+array[self.ys, self.xs]
        flat_blocked = mask[self.ys, self.xs]
        keep = ~flat_blocked[self.origins]&~flat_blocked[self.targets]
        # Reverse edge B->A costs entering B in the forward graph A->B.
        self.matrix = csr_matrix((flat_costs[self.targets[keep]],
                                  (self.targets[keep], self.origins[keep])),
                                 shape=(len(self.xs), len(self.xs)))
        self.blocked = set(blocked)
        self.rebuilds += 1

    def route(self, start, key, cells, free, occupied, *, frontier_penalty=12.):
        if not self.cache_enabled:
            self.fields.pop(key,None)
        if key in self.fields:
            self.hits += 1
        else:
            if len(self.fields) >= self.maximum_fields:
                return None
            self.misses += 1
            seeds = [int(self.ids[y, x]) for x, y in cells if (x, y) not in self.blocked]
            if not seeds:
                return None
            self.fields[key] = dijkstra(self.matrix, indices=seeds, min_only=True,
                return_predecessors=True)
        distances, previous, sources = self.fields[key]
        node = int(self.ids[start[1], start[0]])
        if node < 0:
            return None
        prefix = []
        if not np.isfinite(distances[node]):
            # A blocked origin may escape through a free adjacent cell, as in
            # the existing contract; it never makes a blocked next step legal.
            neighbors = [(distances[self.ids[y, x]], self.ids[y, x])
                         for x, y in self.graph.get_neighbors(*start)
                         if (x, y) not in self.blocked]
            if not neighbors or not np.isfinite(min(neighbors)[0]):
                return None
            node = int(min(neighbors)[1]); prefix = [start]
        path = prefix+[(int(self.xs[node]), int(self.ys[node]))]
        while previous[node] >= 0:
            node = int(previous[node]); path.append((int(self.xs[node]), int(self.ys[node])))
        # Choose an individual free place behind the entry frontier; never
        # share positions. Small bounded BFS is confined to the meeting area.
        region = set(cells); goals = set(free); root = path[-1]
        queue = deque([root]); parents = {root: None}; depth = {root: 0}
        candidates = []
        xs, ys = zip(*cells); x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        while queue:
            point = queue.popleft(); x, y = point
            if point in goals:
                inward = min(x-x0, x1-x, y-y0, y1-y)
                candidates.append((depth[point]+frontier_penalty/(1+inward), point))
            for q in self.graph.get_neighbors(x, y):
                if q in region and q not in parents and q not in self.blocked and q not in occupied:
                    parents[q] = point; depth[q] = depth[point]+1; queue.append(q)
        if not candidates:
            return None
        tail = [min(candidates)[1]]
        while parents[tail[-1]] is not None:
            tail.append(parents[tail[-1]])
        tail.reverse()
        # A guide can enter/leave a non-convex area. Remove any loop introduced
        # by its local tail, preserving cardinal adjacency and gateway validity.
        result, indices = [], {}
        for point in path+tail[1:]:
            if point in indices:
                result = result[:indices[point]+1]; indices = {p:i for i,p in enumerate(result)}
            else:
                indices[point] = len(result); result.append(point)
        self.usage += 1
        return result
