"""Ventana de la futura aplicacion unificada, SOLO estructura (14.4.1).

No instancia motores de fuego, humo, rutas ni personas. La integracion
verdadera ocurre en las fases posteriores. No escribe archivos.
"""
from __future__ import annotations

from .model import CampusSnapshot
from .presentation import (BACKGROUND, COLORS, FOOTER_H, HEADER_H, MUTED,
                           PANEL, TEXT, draw_panels, rect_map)
from .viewport import Viewport


class DisasterCommandCenterApp:
    def __init__(self, snapshot: CampusSnapshot):
        self.snapshot = snapshot
        self.camera = Viewport(snapshot.width, snapshot.height)
        self.labels = True
        self.grid = False
        self.accesses = True
        self.drag = False
        self.message = 'Vista inicial lista'

    @staticmethod
    def _map_surface(pygame, snapshot):
        surface = pygame.Surface((snapshot.width, snapshot.height))
        for y, row in enumerate(snapshot.terrain):
            for x, terrain in enumerate(row):
                surface.set_at((x, y), COLORS[terrain])
        return surface

    def run(self, *, smoke_test: bool = False):
        # Importar pygame solo al abrir el visor. Pruebas estructurales
        # pueden importar el paquete sin pantalla ni pygame instalado.
        import pygame
        pygame.init()
        screen = None
        try:
            screen = pygame.display.set_mode((1320, 830), pygame.RESIZABLE)
            pygame.display.set_caption('Disaster Command Center | App unificada (estructura 14.4.1)')
            font_big = pygame.font.SysFont('arial', 23, bold=True)
            font_med = pygame.font.SysFont('arial', 17, bold=True)
            font_small = pygame.font.SysFont('arial', 13)
            font_label = pygame.font.SysFont('arial', 12, bold=True)
            fonts = (font_big, font_med, font_small)
            map_surface = self._map_surface(pygame, self.snapshot)
            clock = pygame.time.Clock()

            def map_area():
                return pygame.Rect(*rect_map(*screen.get_size()))

            self.camera.fit(tuple(map_area()))
            print(f'[OK] Aplicacion base lista: {self.snapshot.width} x {self.snapshot.height}; '
                  f'edificios={self.snapshot.building_count}; accesos={len(self.snapshot.entrances)}')
            print('F encuadrar, N nombres, G cuadricula, P accesos, rueda zoom, '
                  'clic derecho arrastrar, ESC salir.')
            if smoke_test:
                print('[INFO] Prueba grafica breve: se renderizaran tres fotogramas.')

            running = True
            frames = 0
            while running:
                dt = clock.tick(45) / 1000.0
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.VIDEORESIZE:
                        new_size = max(400, event.w), max(320, event.h)
                        screen = pygame.display.set_mode(new_size, pygame.RESIZABLE)
                        self.camera.fit(tuple(map_area()))
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            running = False
                        elif event.key == pygame.K_f:
                            self.camera.fit(tuple(map_area()))
                        elif event.key == pygame.K_n:
                            self.labels = not self.labels
                        elif event.key == pygame.K_g:
                            self.grid = not self.grid
                        elif event.key == pygame.K_p:
                            self.accesses = not self.accesses
                    elif event.type == pygame.MOUSEWHEEL:
                        mx, my = pygame.mouse.get_pos()
                        if map_area().collidepoint(mx, my):
                            self.camera.zoom_at(mx, my, event.y)
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                        self.drag = map_area().collidepoint(event.pos)
                    elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                        self.drag = False
                    elif event.type == pygame.MOUSEMOTION and self.drag:
                        self.camera.pan(*event.rel)

                sw, sh = screen.get_size()
                area = map_area()
                screen.fill(BACKGROUND)
                screen.set_clip(area)
                size = (max(1, round(self.snapshot.width*self.camera.zoom)),
                        max(1, round(self.snapshot.height*self.camera.zoom)))
                picture = pygame.transform.scale(map_surface, size)
                px, py = self.camera.project(0, 0)
                screen.blit(picture, (px, py))

                if self.grid and self.camera.zoom >= 8:
                    for x in range(self.snapshot.width+1):
                        sx, _ = self.camera.project(x, 0)
                        pygame.draw.line(screen, (123, 143, 160), (sx, area.top), (sx, area.bottom), 1)
                    for y in range(self.snapshot.height+1):
                        _, sy = self.camera.project(0, y)
                        pygame.draw.line(screen, (123, 143, 160), (area.left, sy), (area.right, sy), 1)

                if self.accesses:
                    for _building, ax, ay in self.snapshot.entrances:
                        cx, cy = self.camera.project(ax+0.5, ay+0.5)
                        if area.collidepoint(cx, cy):
                            pygame.draw.circle(screen, (251, 208, 92), (cx, cy),
                                               max(2, min(7, int(self.camera.zoom*.4))), 1)

                if self.labels and self.camera.zoom >= 4.3:
                    for label, (cx, cy) in self.snapshot.centers.items():
                        sx, sy = self.camera.project(cx, cy)
                        if area.collidepoint(sx, sy):
                            words = font_label.render(label, True, TEXT)
                            tag = words.get_rect(center=(sx, sy))
                            pygame.draw.rect(screen, (21, 40, 59), tag.inflate(7, 4), border_radius=3)
                            screen.blit(words, tag)
                screen.set_clip(None)
                pygame.draw.rect(screen, MUTED, area, 1)
                draw_panels(screen, self.snapshot, fonts, show_accesses=self.accesses,
                            show_grid=self.grid, show_labels=self.labels,
                            fps=clock.get_fps(), message=self.message)
                pygame.display.flip()
                frames += 1
                if smoke_test and frames >= 3:
                    running = False

            if smoke_test:
                print('Paso 14.4.1: smoke test grafico OK (3 fotogramas).')
        finally:
            pygame.quit()
