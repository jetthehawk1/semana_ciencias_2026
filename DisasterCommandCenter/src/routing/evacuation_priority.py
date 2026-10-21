
class EvacuationPriority:
    """
    Calcula prioridades para evacuación simulada.

    Un valor mayor representa mayor prioridad.
    """

    RISK_WEIGHTS = {
        "low": 0,
        "medium": 20,
        "high": 40,
        "critical": 60,
    }

    def __init__(self):
        self.priorities = {}

    def calculate_priority(
        self,
        person_id,
        risk_level="low",
        needs_assistance=False,
        waiting_turns=0,
    ):
        risk_score = self.RISK_WEIGHTS.get(
            risk_level, 0
        )

        assistance_score = (
            30 if needs_assistance else 0
        )

        waiting_score = min(
            max(0, waiting_turns) * 2,
            20,
        )

        score = (
            risk_score
            + assistance_score
            + waiting_score
        )

        self.priorities[person_id] = score

        return score

    def get_priority(self, person_id):
        return self.priorities.get(
            person_id, 0
        )

    def rank_people(self, people_data):
        """
        Ordena personas de mayor a menor prioridad.

        people_data:
            Lista de diccionarios con información
            de riesgo y asistencia.
        """

        ranked = []

        for data in people_data:
            person_id = data["person_id"]

            score = self.calculate_priority(
                person_id=person_id,
                risk_level=data.get(
                    "risk_level", "low"
                ),
                needs_assistance=data.get(
                    "needs_assistance", False
                ),
                waiting_turns=data.get(
                    "waiting_turns", 0
                ),
            )

            ranked.append({
                "person_id": person_id,
                "priority": score,
            })

        return sorted(
            ranked,
            key=lambda item: (
                -item["priority"],
                item["person_id"],
            ),
        )
