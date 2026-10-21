
from copy import deepcopy

from routing.dynamic_replanner import DynamicReplanner


class RoutingController:
    """
    Coordina movimiento y recálculo de rutas.

    Utiliza ExternalRouteFollower de Persona 1
    sin modificar sus archivos.
    """

    def __init__(self, graph, follower, manager, request):
        self.graph = graph
        self.follower = follower
        self.manager = manager
        self.request = deepcopy(request)

        self.replanner = DynamicReplanner(
            graph=graph,
            follower=follower,
            manager=manager,
        )

        self.turn = 0

    def step(self, blocked_cells=None):
        """
        Ejecuta un turno de simulación.

        blocked_cells:
            Lista actual de celdas bloqueadas.

        Devuelve un resumen del turno.
        """

        self.turn += 1

        # Actualizar los riesgos cuando se proporcionen.
        if blocked_cells is not None:
            self.request["blocked_cells"] = deepcopy(
                blocked_cells
            )

        self.request["turn"] = self.turn

        # Informar al controlador de Persona 1
        # sobre los obstáculos actuales.
        self.follower.set_blocked_cells(
            self.request["blocked_cells"]
        )

        # Intentar mover a las personas.
        moved = self.follower.step()

        # Buscar rutas bloqueadas y recalcular.
        replanned = []

        for person_data in self.request["people"]:
            person_id = person_data["person_id"]

            if self.follower.route_status(
                person_id
            ) != "bloqueada_por_riesgo":
                continue

            success = self.replanner.replan_if_blocked(
                self.request,
                person_id,
            )

            if success:
                replanned.append(person_id)

                # Sincronizar el inicio de la ruta
                # con la posición actual.
                person = self.manager.get_person(
                    person_id
                )

                person_data["start"] = {
                    "x": person.x,
                    "y": person.y,
                }

        return {
            "turn": self.turn,
            "moved": moved,
            "replanned": replanned,
            "replan_count": self.replanner.replan_count,
        }
