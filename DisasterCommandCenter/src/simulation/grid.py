
from simulation.cell import Cell


class Grid:
    """Administra las celdas de la cuadrícula del campus."""

    def __init__(self, width: int, height: int):
        if width <= 0 or height <= 0:
            raise ValueError(
                "El ancho y el alto deben ser mayores que cero."
            )

        self.width = width
        self.height = height

        # Creamos una celda para cada posición de la cuadrícula.
        self.cells = [
            [
                Cell(x=x, y=y)
                for x in range(width)
            ]
            for y in range(height)
        ]

    def is_inside(self, x: int, y: int) -> bool:
        """Indica si unas coordenadas están dentro de la cuadrícula."""
        return (
            0 <= x < self.width
            and 0 <= y < self.height
        )

    def get_cell(self, x: int, y: int) -> Cell:
        """Devuelve la celda de una posición concreta."""
        if not self.is_inside(x, y):
            raise IndexError(
                f"La posición ({x}, {y}) está fuera de la cuadrícula."
            )

        return self.cells[y][x]

    def get_neighbors(self, x: int, y: int) -> list[Cell]:
        """Devuelve las celdas vecinas en las cuatro direcciones."""
        if not self.is_inside(x, y):
            raise IndexError(
                f"La posición ({x}, {y}) está fuera de la cuadrícula."
            )

        directions = [
            (0, -1),  # Arriba
            (0, 1),   # Abajo
            (-1, 0),  # Izquierda
            (1, 0),   # Derecha
        ]

        neighbors = []

        for dx, dy in directions:
            nx = x + dx
            ny = y + dy

            if self.is_inside(nx, ny):
                neighbors.append(self.get_cell(nx, ny))

        return neighbors
