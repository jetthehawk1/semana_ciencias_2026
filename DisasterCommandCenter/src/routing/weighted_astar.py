
import heapq
from itertools import count


def weighted_astar(
    graph,
    start,
    goal,
    congestion_manager=None,
    blocked_cells=None,
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

        if congestion_manager is None:
            return base_cost

        extra = congestion_manager.get_cost(
            position[0],
            position[1],
        )

        return base_cost + max(0.0, extra)

    frontier = []
    sequence = count()

    heapq.heappush(
        frontier,
        (heuristic(start, goal), next(sequence), start),
    )

    came_from = {}
    g_score = {start: 0.0}

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

            tentative = (
                g_score[current]
                + movement_cost(neighbor)
            )

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
