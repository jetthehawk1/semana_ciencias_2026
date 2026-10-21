
from copy import deepcopy

from routing.route_adapter import calculate_route_response


class DynamicReplanner:
    """
    Recalcula rutas bloqueadas utilizando A*.

    Evita repetir intentos fallidos mientras
    las condiciones permanezcan iguales.
    """

    def __init__(self, graph, follower, manager):
        self.graph = graph
        self.follower = follower
        self.manager = manager

        self.replan_count = 0
        self.failed_attempts = 0

        # Guarda las condiciones de búsquedas fallidas.
        self.failed_signatures = {}

    def replan_if_blocked(self, request, person_id):

        status = self.follower.route_status(person_id)

        if status != "bloqueada_por_riesgo":
            return False

        person = self.manager.get_person(person_id)

        if person is None:
            return False

        updated_request = deepcopy(request)

        person_data = None

        for item in updated_request["people"]:
            if item["person_id"] == person_id:
                person_data = item
                break

        if person_data is None:
            return False

        current_position = {
            "x": person.x,
            "y": person.y,
        }

        person_data["start"] = current_position

        # Identificar las condiciones actuales.
        blocked_signature = tuple(
            sorted(
                (cell["x"], cell["y"])
                for cell in updated_request["blocked_cells"]
            )
        )

        goal = person_data["goal"]

        signature = (
            person.x,
            person.y,
            goal["x"],
            goal["y"],
            blocked_signature,
        )

        # No repetir una búsqueda que ya falló
        # bajo las mismas condiciones.
        if self.failed_signatures.get(person_id) == signature:
            return False

        route_id = (
            f"ruta-recalculada-{person_id}-"
            f"{self.replan_count + 1}"
        )

        alternative = calculate_route_response(
            self.graph,
            updated_request,
            person_id=person_id,
            route_id=route_id,
        )

        if alternative is None:
            self.failed_attempts += 1
            self.failed_signatures[person_id] = signature
            return False

        # Registrar la nueva ruta.
        self.follower.set_request(updated_request)
        self.follower.submit_route(alternative)

        self.replan_count += 1

        # Eliminar el último fallo de esta persona.
        self.failed_signatures.pop(person_id, None)

        return True
