
from collections import defaultdict


class CongestionManager:
    """
    Calcula la congestión del campus según
    las posiciones actuales de las personas.

    No modifica el mapa ni la simulación.
    """

    def __init__(
        self,
        radius=2,
        congestion_weight=2.0,
    ):
        self.radius = radius
        self.congestion_weight = congestion_weight

        self.occupancy = defaultdict(int)
        self.congestion_map = {}

    def update(self, people):
        """
        Actualiza la información de congestión.

        people:
            Lista de objetos Person.
        """

        self.occupancy.clear()
        self.congestion_map.clear()

        positions = []

        for person in people:
            position = (person.x, person.y)

            self.occupancy[position] += 1
            positions.append(position)

        # Calcular congestión alrededor
        # de las posiciones ocupadas.
        for px, py in positions:

            for dx in range(
                -self.radius,
                self.radius + 1
            ):
                for dy in range(
                    -self.radius,
                    self.radius + 1
                ):

                    distance = abs(dx) + abs(dy)

                    if distance > self.radius:
                        continue

                    x = px + dx
                    y = py + dy

                    influence = (
                        self.radius - distance + 1
                    )

                    self.congestion_map[(x, y)] = (
                        self.congestion_map.get(
                            (x, y), 0
                        ) + influence
                    )

    def get_congestion(self, x, y):
        """
        Devuelve la congestión estimada
        de una celda.
        """

        return self.congestion_map.get(
            (x, y), 0
        )

    def get_cost(self, x, y):
        """
        Devuelve el costo adicional
        por congestión.
        """

        congestion = self.get_congestion(x, y)

        return (
            congestion
            * self.congestion_weight
        )

    def get_occupancy(self, x, y):
        """
        Devuelve cuántas personas
        ocupan una celda.
        """

        return self.occupancy.get(
            (x, y), 0
        )

    def get_most_congested(self, limit=10):
        """
        Devuelve las celdas con mayor
        congestión estimada.
        """

        ordered = sorted(
            self.congestion_map.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        return ordered[:limit]
