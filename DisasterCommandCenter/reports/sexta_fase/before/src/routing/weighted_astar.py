
import heapq
from itertools import count


def weighted_astar(
    graph,
    start,
    goal,
    congestion_manager=None,
    blocked_cells=None,
    risk_field=None,
):
    """
    A* con costos adicionales por congestión.

    start y goal son tuplas (x, y).
    Devuelve una lista de tuplas o None.
    """

    blocked = set()

    for cell in blocked_cells or []:
        if isinstance(cell, dict):
            blocked.add((cell["x"], cell["y"]))
        else:
            blocked.add(tuple(cell))

    if not graph.is_valid(*start):
        return None

    if not graph.is_valid(*goal):
        return None

    if start in blocked or goal in blocked:
        return None

    def heuristic(a, b):
        return (
            abs(a[0] - b[0])
            + abs(a[1] - b[1])
        )

    def movement_cost(position):
        base_cost = 1.0

        extra = 0.0 if congestion_manager is None else congestion_manager.get_cost(
            position[0],
            position[1],
        )

        risk = risk_field.risk_cost(*position) if risk_field is not None else 0.0
        return base_cost + max(0.0, extra) + max(0.0, risk)

    frontier = []
    sequence = count()

    heapq.heappush(
        frontier,
        (heuristic(start, goal), next(sequence), start),
    )

    came_from = {}
    g_score = {start: 0.0}
    # Costs are immutable during one synchronous search. The same cell can be
    # visited from several edges; memoizing its cost changes neither A*, its
    # heuristic, tie order nor weights. A new search always gets a fresh cache.
    movement_cost_cache = {}

    while frontier:
        priority, _, current = heapq.heappop(
            frontier
        )

        expected_priority = (
            g_score[current]
            + heuristic(current, goal)
        )

        if priority > expected_priority + 1e-9:
            continue

        if current == goal:
            path = [current]

            while current in came_from:
                current = came_from[current]
                path.append(current)

            path.reverse()
            return path

        for neighbor in graph.neighbors(*current):

            if neighbor in blocked:
                continue

            step_cost = movement_cost_cache.get(neighbor)
            if step_cost is None:
                step_cost = movement_cost(neighbor)
                movement_cost_cache[neighbor] = step_cost
            tentative = g_score[current] + step_cost

            if tentative < g_score.get(
                neighbor,
                float("inf"),
            ):
                came_from[neighbor] = current
                g_score[neighbor] = tentative

                f_score = (
                    tentative
                    + heuristic(neighbor, goal)
                )

                heapq.heappush(
                    frontier,
                    (
                        f_score,
                        next(sequence),
                        neighbor,
                    ),
                )

    return None
