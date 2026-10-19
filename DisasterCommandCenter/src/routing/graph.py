
class CampusGraph:
    """Grafo de movimiento exterior del campus."""

    ALLOWED_TERRAINS = {"floor", "road"}

    def __init__(self, campus_map):
        self.campus_map = campus_map
        self.width = campus_map.width
        self.height = campus_map.height

    def is_valid(self, x, y):
        """Comprueba si una celda puede recorrerse."""

        if not (0 <= x < self.width and 0 <= y < self.height):
            return False

        cell = self.campus_map.get_cell(x, y)

        return cell.terrain_type in self.ALLOWED_TERRAINS

    def get_neighbors(self, x, y):
        """Obtiene vecinos transitables en 4 direcciones."""

        if not self.is_valid(x, y):
            return []

        directions = [
            (0, -1),  # Arriba
            (1, 0),   # Derecha
            (0, 1),   # Abajo
            (-1, 0),  # Izquierda
        ]

        neighbors = []

        for dx, dy in directions:
            nx = x + dx
            ny = y + dy

            if self.is_valid(nx, ny):
                neighbors.append((nx, ny))

        return neighbors
