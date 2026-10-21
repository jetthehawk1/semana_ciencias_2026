"""Paneles y colores del cascaron grafico. Depende de pygame solo al dibujar."""
from __future__ import annotations

COLORS = {
    'grass': (97, 130, 107),
    'building': (65, 112, 158),
    'floor': (211, 214, 208),
    'road': (153, 154, 147),
}
BACKGROUND = (19, 29, 42)
PANEL = (30, 45, 62)
TEXT = (239, 245, 248)
MUTED = (175, 193, 208)
HEADER_H = 82
FOOTER_H = 51
SIDEBAR_W = 316


def rect_map(screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
    # Deja un ancho minimo visible incluso si el usuario redimensiona mucho.
    sidebar = min(SIDEBAR_W, max(120, screen_w // 3))
    return (0, HEADER_H, max(1, screen_w-sidebar), max(1, screen_h-HEADER_H-FOOTER_H))


def draw_panels(screen, snapshot, fonts, *, show_accesses: bool, show_grid: bool,
                show_labels: bool, fps: float, message: str) -> None:
    import pygame
    width, height = screen.get_size()
    _, top, map_w, _ = rect_map(width, height)
    side_x = map_w
    pygame.draw.rect(screen, PANEL, (0, 0, width, HEADER_H))
    pygame.draw.rect(screen, PANEL, (side_x, top, width-side_x, height-top))
    pygame.draw.rect(screen, PANEL, (0, height-FOOTER_H, width, FOOTER_H))

    big, med, small = fonts

    def line(text, x, y, font=small, color=TEXT):
        if y < height-20:
            screen.blit(font.render(str(text), True, color), (x, y))

    line('DISASTER COMMAND CENTER', 18, 13, big)
    line('Paso 14.4.1  |  Estructura de aplicacion  |  Sin simulacion activa', 19, 48, small, MUTED)
    y = top + 17
    line('PANEL DE CONTROL', side_x+14, y, med)
    y += 43
    for title, value in [
        ('Campus', 'Ensenada - hasta E1'),
        ('Cuadricula', f'{snapshot.width} x {snapshot.height}'),
        ('Zonas del plano', '502 (referencia)' if snapshot.width == 160 else 'Segun campus.json'),
        ('Edificios', str(snapshot.building_count)),
        ('Accesos', str(len(snapshot.entrances))),
        ('Transitable', str(snapshot.terrain_count.get('floor', 0) + snapshot.terrain_count.get('road', 0))),
        ('Estado', 'VISOR DE BASE'),
    ]:
        line(title + ':', side_x+14, y, small, MUTED)
        y += 18
        line(value, side_x+14, y, med)
        y += 36

    y += 5
    for label, value in [
        ('Fuego / humo', 'Pendiente 14.4.2'),
        ('Personas', 'Pendiente 14.4.2'),
        ('Sensores', 'Pendiente 14.4.3'),
        ('Selector de modo', 'Pendiente 14.4.4'),
    ]:
        line(label, side_x+14, y, small, MUTED)
        y += 17
        line(value, side_x+14, y, small)
        y += 30

    line(f'Mapa: F encuadrar | rueda zoom | clic derecho arrastrar | N nombres | G cuadricula | P accesos | ESC salir', 15, height-40, small)
    line(f'{message}  |  FPS {fps:.0f}  |  Grid {"si" if show_grid else "no"}  |  Nombres {"si" if show_labels else "no"}  |  Accesos {"si" if show_accesses else "no"}', 15, height-21, small, MUTED)
