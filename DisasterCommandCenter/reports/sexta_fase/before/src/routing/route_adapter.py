
from routing.astar import astar


SCHEMA_VERSION = "1.0"


def calculate_route_response(
    graph,
    request,
    person_id,
    route_id="ruta-001",
):
    """
    Calcula una ruta A* para una persona incluida
    en una solicitud de route_gateway.py.

    Devuelve un diccionario compatible con
    ExternalRouteFollower.submit_route().
    """

    if request.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Versión de esquema incompatible.")

    if (
        request.get("width") != graph.width
        or request.get("height") != graph.height
    ):
        raise ValueError("Dimensiones incompatibles.")

    people = request.get("people", [])

    person = next(
        (
            item for item in people
            if item["person_id"] == person_id
        ),
        None,
    )

    if person is None:
        raise ValueError(
            f"Persona no encontrada: {person_id}"
        )

    start = (
        person["start"]["x"],
        person["start"]["y"],
    )

    goal = (
        person["goal"]["x"],
        person["goal"]["y"],
    )

    blocked = {
        (cell["x"], cell["y"])
        for cell in request.get("blocked_cells", [])
    }

    if start in blocked or goal in blocked:
        return None

    # Vista del grafo que excluye obstáculos dinámicos.
    class SafeGraph:
        def __init__(self, base_graph):
            self.base_graph = base_graph

        def is_valid(self, x, y):
            return (
                (x, y) not in blocked
                and self.base_graph.is_valid(x, y)
            )

        def get_neighbors(self, x, y):
            if not self.is_valid(x, y):
                return []

            return [
                (nx, ny)
                for nx, ny in self.base_graph.get_neighbors(x, y)
                if self.is_valid(nx, ny)
            ]

    path = astar(SafeGraph(graph), start, goal)

    if path is None:
        return None

    return {
        "schema_version": SCHEMA_VERSION,
        "map_name": request["map_name"],
        "width": graph.width,
        "height": graph.height,
        "route_id": route_id,
        "person_id": person_id,
        "destination_id": person["destination_id"],
        "goal": {
            "x": goal[0],
            "y": goal[1],
        },
        "path": [
            {"x": x, "y": y}
            for x, y in path
        ],
    }
