"""Mascara de riesgo exterior consumida por el routing existente."""
from __future__ import annotations


def exterior_blocked_cells(burning, concentrations, terrain, *, smoke_threshold=.65,
                           vegetation_buffer=1):
    if type(vegetation_buffer) is not int or not 0 <= vegetation_buffer <= 3:
        raise ValueError("El margen vegetal debe ser de 0 a 3 celdas finas.")
    height, width = len(terrain), len(terrain[0])
    fires = set(burning)
    blocked = fires | {(x, y) for y, row in enumerate(concentrations)
                       for x, amount in enumerate(row) if amount >= smoke_threshold}
    for x, y in fires:
        if terrain[y][x] != "grass":
            continue
        for dy in range(-vegetation_buffer, vegetation_buffer+1):
            for dx in range(-vegetation_buffer, vegetation_buffer+1):
                nx, ny = x+dx, y+dy
                if (abs(dx)+abs(dy) <= vegetation_buffer and 0 <= nx < width and 0 <= ny < height
                        and terrain[ny][nx] in {"floor", "road"}):
                    blocked.add((nx, ny))
    return blocked
