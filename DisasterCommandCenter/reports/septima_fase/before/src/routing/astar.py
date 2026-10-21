
import heapq


def manhattan(a, b):
    """Calcula la distancia Manhattan entre dos celdas."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(graph, start, goal):
    """
    Busca una ruta entre start y goal usando A*.

    Devuelve:
        Lista de coordenadas [(x, y), ...]
        o None si no existe una ruta.
    """

    start = tuple(start)
    goal = tuple(goal)

    # Comprobar que inicio y destino sean transitables.
    if not graph.is_valid(*start):
        return None

    if not graph.is_valid(*goal):
        return None

    # Si ya estamos en el destino.
    if start == goal:
        return [start]

    # Cola de prioridad: (f, coordenada)
    open_set = []
    heapq.heappush(
        open_set,
        (manhattan(start, goal), start)
    )

    # Para reconstruir el camino.
    came_from = {}

    # Mejor distancia conocida desde el inicio.
    g_score = {start: 0}

    while open_set:

        _, current = heapq.heappop(open_set)

        if current == goal:

            path = [current]

            while current in came_from:
                current = came_from[current]
                path.append(current)

            path.reverse()
            return path

        for neighbor in graph.get_neighbors(*current):

            tentative_g = g_score[current] + 1

            if tentative_g < g_score.get(
                neighbor, float("inf")
            ):

                came_from[neighbor] = current
                g_score[neighbor] = tentative_g

                f_score = (
                    tentative_g
                    + manhattan(neighbor, goal)
                )

                heapq.heappush(
                    open_set,
                    (f_score, neighbor)
                )

    # No se encontró camino.
    return None
