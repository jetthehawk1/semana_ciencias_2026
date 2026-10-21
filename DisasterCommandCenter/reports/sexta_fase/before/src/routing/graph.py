
class CampusGraph:
    """Grafo de movimiento exterior del campus."""

    ALLOWED_TERRAINS = {"floor", "road"}

    def __init__(self, campus_map):
        self.campus_map = campus_map
        self.width = campus_map.width
        self.height = campus_map.height
        self._static_neighbors = None

    def cache_static_topology(self):
        """Opt-in para mapas inmutables: riesgos siguen entrando por blocked_cells.

        Los grafos editables de tests/herramientas conservan consultas en vivo.
        """
        self._static_valid = tuple(tuple(self.campus_map.get_cell(x, y).terrain_type in self.ALLOWED_TERRAINS
                                        for x in range(self.width)) for y in range(self.height))
        self._static_neighbors = tuple(tuple(tuple((x+dx, y+dy) for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0))
            if 0 <= x+dx < self.width and 0 <= y+dy < self.height and self._static_valid[y+dy][x+dx])
            if self._static_valid[y][x] else () for x in range(self.width)) for y in range(self.height))
        return self

    def is_valid(self, x, y):
        """Comprueba si una celda puede recorrerse."""

        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        if self._static_neighbors is not None:
            return self._static_valid[y][x]

        cell = self.campus_map.get_cell(x, y)

        return cell.terrain_type in self.ALLOWED_TERRAINS

    def get_neighbors(self, x, y):
        """Obtiene vecinos transitables en 4 direcciones."""

        if self._static_neighbors is not None:
            return list(self._static_neighbors[y][x]) if 0 <= x < self.width and 0 <= y < self.height else []

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

    def neighbors(self, x, y):
        """Alias requerido por weighted_astar; conserva los mismos vecinos."""
        return self.get_neighbors(x, y)
