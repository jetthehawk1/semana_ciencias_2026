
from copy import deepcopy

from routing.congestion import CongestionManager
from routing.congestion_route_adapter import (
    calculate_congestion_route,
)
from routing.evacuation_priority import EvacuationPriority


class EvacuationOptimizer:
    """
    Optimizador experimental de evacuación.

    Combina:
    - Congestión
    - Prioridades
    - Rutas A* ponderadas
    - Contrato JSON de Persona 1
    """

    def __init__(
        self,
        graph,
        congestion_radius=2,
        congestion_weight=2.0,
    ):
        self.graph = graph

        self.congestion = CongestionManager(
            radius=congestion_radius,
            congestion_weight=congestion_weight,
        )

        self.priority = EvacuationPriority()

        self.optimization_count = 0

    def optimize(
        self,
        request,
        people,
        priority_data=None,
    ):
        """
        Calcula rutas para todas las personas.

        request:
            Solicitud JSON de rutas.

        people:
            Lista de objetos Person.

        priority_data:
            Información opcional de prioridades.

        Devuelve un resumen con rutas y personas
        para las que no se encontró camino.
        """

        updated_request = deepcopy(request)

        # Actualizar congestión.
        self.congestion.update(people)

        # Sincronizar posiciones actuales.
        people_by_id = {
            person.person_id: person
            for person in people
        }

        for data in updated_request["people"]:
            person = people_by_id.get(
                data["person_id"]
            )

            if person is not None:
                data["start"] = {
                    "x": person.x,
                    "y": person.y,
                }

        # Preparar prioridades.
        if priority_data is None:
            priority_data = [
                {
                    "person_id": data["person_id"],
                    "risk_level": "low",
                }
                for data in updated_request["people"]
            ]

        ranked = self.priority.rank_people(
            priority_data
        )

        valid_ids = {
            data["person_id"]
            for data in updated_request["people"]
        }

        ranked_ids = [
            item["person_id"]
            for item in ranked
            if item["person_id"] in valid_ids
        ]

        # Incluir personas sin datos de prioridad.
        for data in updated_request["people"]:
            person_id = data["person_id"]

            if person_id not in ranked_ids:
                ranked_ids.append(person_id)

        routes = []
        failed = []

        # Calcular rutas en orden de prioridad.
        for person_id in ranked_ids:

            route = calculate_congestion_route(
                graph=self.graph,
                request=updated_request,
                person_id=person_id,
                congestion_manager=self.congestion,
                route_id=(
                    f"optimized-{person_id}-"
                    f"{self.optimization_count + 1}"
                ),
            )

            if route is None:
                failed.append(person_id)
                continue

            routes.append(route)

        self.optimization_count += 1

        return {
            "routes": routes,
            "failed": failed,
            "priority_order": ranked_ids,
            "optimization_count": (
                self.optimization_count
            ),
        }
