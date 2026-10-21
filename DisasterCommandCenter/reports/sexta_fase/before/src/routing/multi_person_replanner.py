
from copy import deepcopy

from routing.route_adapter import calculate_route_response


class MultiPersonReplanner:
    """
    Coordina el recálculo de rutas de varias personas.

    Conserva una solicitud conjunta para mantener
    la información de todos los participantes.
    """

    def __init__(self, graph, follower, manager):
        self.graph = graph
        self.follower = follower
        self.manager = manager

        self.replan_count = 0
        self.failed_signatures = {}
        self.failed_attempts = 0

    def replan_blocked(self, request):
        """
        Recalcula rutas bloqueadas por riesgos.

        Devuelve una lista con los identificadores
        de las personas que recibieron nuevas rutas.
        """

        updated_request = deepcopy(request)
        replanned = []

        # Mantener actualizadas las posiciones.
        for data in updated_request["people"]:
            person = self.manager.get_person(
                data["person_id"]
            )

            if person is not None:
                data["start"] = {
                    "x": person.x,
                    "y": person.y,
                }

        # Identificar personas con rutas bloqueadas.
        blocked_ids = []

        for data in updated_request["people"]:
            person_id = data["person_id"]

            if (
                self.follower.route_status(person_id)
                == "bloqueada_por_riesgo"
            ):
                blocked_ids.append(person_id)

        # Calcular alternativas antes de registrarlas.
        alternatives = []

        for person_id in blocked_ids:
            data = next(
                item for item in updated_request["people"]
                if item["person_id"] == person_id
            )

            person = self.manager.get_person(person_id)

            if person is None:
                continue

            blocked_signature = tuple(
                sorted(
                    (cell["x"], cell["y"])
                    for cell in updated_request["blocked_cells"]
                )
            )

            goal = data["goal"]

            signature = (
                person.x,
                person.y,
                goal["x"],
                goal["y"],
                blocked_signature,
            )

            if (
                self.failed_signatures.get(person_id)
                == signature
            ):
                continue

            route = calculate_route_response(
                self.graph,
                updated_request,
                person_id=person_id,
                route_id=(
                    f"multi-replan-{person_id}-"
                    f"{self.replan_count + len(alternatives) + 1}"
                ),
            )

            if route is None:
                self.failed_attempts += 1
                self.failed_signatures[person_id] = signature
                continue

            alternatives.append((person_id, route))

        # Registrar las rutas calculadas.
        #
        # Se actualiza una sola solicitud conjunta.
        if alternatives:
            self.follower.set_request(updated_request)

            for person_id, route in alternatives:
                self.follower.submit_route(route)

                self.failed_signatures.pop(
                    person_id, None
                )

                replanned.append(person_id)
                self.replan_count += 1

        return replanned
