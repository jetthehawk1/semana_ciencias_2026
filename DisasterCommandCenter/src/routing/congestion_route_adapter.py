
from routing.weighted_astar import weighted_astar


def calculate_congestion_route(
    graph,
    request,
    person_id,
    congestion_manager,
    route_id="ruta-congestion",
    risk_field=None,
):
    """
    Calcula una ruta que considera
    obstáculos y congestión.

    Devuelve una respuesta compatible
    con el contrato JSON de rutas.
    """

    person_data = None

    for person in request["people"]:
        if person["person_id"] == person_id:
            person_data = person
            break

    if person_data is None:
        return None

    start_data = person_data["start"]
    goal_data = person_data["goal"]

    start = (
        start_data["x"],
        start_data["y"],
    )

    goal = (
        goal_data["x"],
        goal_data["y"],
    )

    path = weighted_astar(
        graph=graph,
        start=start,
        goal=goal,
        congestion_manager=congestion_manager,
        blocked_cells=request.get(
            "blocked_cells", []
        ),
        risk_field=risk_field,
    )

    if path is None:
        return None

    return {
        "schema_version": request["schema_version"],
        "map_name": request["map_name"],
        "width": request["width"],
        "height": request["height"],
        "route_id": route_id,
        "person_id": person_id,
        "destination_id": person_data["destination_id"],
        "goal": {
            "x": goal[0],
            "y": goal[1],
        },
        "path": [
            {"x": x, "y": y}
            for x, y in path
        ],
    }
