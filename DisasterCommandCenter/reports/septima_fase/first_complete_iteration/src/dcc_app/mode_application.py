"""Paso 14.4.4: visor unificado con modo real, visible y reversible.

Se extiende el visor de 14.4.3 sin cambiarlo. El bucle grafico se replica
solo para añadir la tecla M y mostrar el modo real (el original no admite
interceptar sus eventos). Las simulaciones siguen teniendo turnos ficticios.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .sensor_application import SensorDisasterApp
from .mode_scene import ModeSensorScene
from .presentation import BACKGROUND, COLORS, FOOTER_H, HEADER_H, MUTED, PANEL, TEXT, rect_map


class ModeSensorDisasterApp(SensorDisasterApp):
    def __init__(self, snapshot, root, *, mode=None, configuracion=None):
        super().__init__(snapshot, root)
        self.scene = ModeSensorScene(root, mode=mode, configuracion=configuracion)
        self.message = 'Modo ' + self.scene.mode + ': A inicia la alarma'

    def _draw_sidebar(self, pygame, screen, fonts, fps):
        # Reutilizar panel 14.4.3 intacto, con una etiqueta visible del modo.
        super()._draw_sidebar(pygame, screen, fonts, fps)
        w, h = screen.get_size()
        left = rect_map(w, h)[2]
        status = f'MODO {self.scene.mode.upper()} | M cambiar antes de A'
        font = fonts[2]
        pygame.draw.rect(screen, PANEL, (left+10, HEADER_H+10, w-left-18, 29))
        screen.blit(font.render(status, True, (94, 237, 185) if self.scene.mode == 'optimizado'
                                else TEXT), (left+13, HEADER_H+17))
        # Identificar sin ambiguedad esta version, tambien en el encabezado.
        pygame.draw.rect(screen, PANEL, (12, 44, min(800, w-20), 25))
        screen.blit(font.render('Paso 14.4.4 | Motores seleccionables, sensores y estadisticas',
                                True, MUTED), (19, 48))
        pygame.draw.rect(screen, PANEL, (0, h-FOOTER_H, left, 20))
        screen.blit(font.render('A alarma | R reinicia | M modo antes de alarma | T escenario | E exportar',
                                True, TEXT), (13, h-40))

    def map_area(self, width, height):
        return rect_map(width, height)

    def run(self, *, smoke_test=False):
        import pygame
        pygame.init()
        try:
            screen = pygame.display.set_mode((1320, 830), pygame.RESIZABLE)
            pygame.display.set_caption(getattr(self, 'window_caption',
                'Disaster Command Center | Selector reversible y sensores 14.4.4'))
            fonts = (pygame.font.SysFont('arial', 22, bold=True),
                     pygame.font.SysFont('arial', 17, bold=True),
                     pygame.font.SysFont('arial', 12))
            font_label = pygame.font.SysFont('arial', 11, bold=True)
            terrain_surface = self._map_surface(pygame, self.snapshot)
            clock = pygame.time.Clock()
            overlays_dirty = True
            smoke_surface = None
            fire_surface = None
            scale_cache = {}

            def area():
                return pygame.Rect(*self.map_area(*screen.get_size()))

            def try_action(fn, *, mark_dirty=True):
                nonlocal overlays_dirty
                try:
                    value = fn()
                    if mark_dirty:
                        overlays_dirty = True
                    return value
                except (ValueError, RuntimeError) as exc:
                    self.message = str(exc)
                    return None

            self.camera.fit(tuple(area()))
            print(f'[OK] App integrada 14.4.4: {self.snapshot.width}x{self.snapshot.height}; '
                  f'personas={len(self.scene.people)}; escenario={self.scene.kind}; '
                  f'modo={self.scene.mode}; sensores={len(self.scene.sensor_positions)}.')
            print('A alarma; ESPACIO pausa; . turno; R reinicia; T cambia escenario antes de A; '
                  'M modo (solo antes de alarma); V viento; [ ] intensidad; H humo; '
                  + getattr(self, 'click_help', 'clic izquierdo agrega foco tras alarma') + '; '
                  'E exportar; S sensores; TAB seleccionar; F encuadrar; N etiquetas; G cuadricula; P accesos; ESC cerrar.')
            frames = 0
            running = True
            while running:
                elapsed = clock.tick(45)/1000.0
                dt = elapsed if hasattr(self, 'advance_playback') else min(elapsed, 0.15)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.VIDEORESIZE:
                        screen = pygame.display.set_mode((max(400, event.w), max(320, event.h)), pygame.RESIZABLE)
                        self.camera.fit(tuple(area()))
                        scale_cache.clear()
                    elif event.type == pygame.KEYDOWN:
                        key = event.key
                        if key == pygame.K_ESCAPE:
                            running = False
                        elif key == pygame.K_a:
                            if self.scene.info['fase'] == 'preparado':
                                try_action(self.scene.start)
                                self.message = 'Alarma iniciada' if self.scene.info['fase'] != 'preparado' else self.message
                                self.accumulator = 0
                        elif key == pygame.K_SPACE:
                            try_action(self.scene.toggle_pause)
                            self.accumulator = 0
                        elif key == pygame.K_PERIOD:
                            if self.scene.info['fase'] == 'pausado':
                                try_action(lambda: self.scene.step(manual=True))
                        elif key == pygame.K_r:
                            try_action(self.scene.reset)
                            self.accumulator = 0
                            self.message = 'Escenario reiniciado; sensores en cero; presiona A'
                        elif key == pygame.K_t:
                            new_kind = try_action(self.scene.toggle_kind)
                            if new_kind:
                                self.message = 'Escenario: ' + new_kind + ' (presiona A)'
                        elif key == pygame.K_m:
                            new_mode = try_action(self.scene.cycle_mode)
                            if new_mode:
                                self.message = 'Modo ' + new_mode + ' (solo esta ventana)'
                                self.accumulator = 0
                        elif key == pygame.K_v:
                            val = try_action(self.scene.cycle_wind)
                            if val:
                                self.message = 'Viento hacia ' + val
                        elif key in (pygame.K_RIGHTBRACKET, pygame.K_LEFTBRACKET):
                            delta = 0.1 if key == pygame.K_RIGHTBRACKET else -0.1
                            try_action(lambda: self.scene.adjust_wind(delta))
                        elif key == pygame.K_e:
                            from pathlib import Path
                            output = (self.scene.root / 'exports' / 'sensores_paso_14_4_4'
                                      / datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
                            paths = try_action(lambda: self.scene.export_readings(output))
                            if paths:
                                self.message = 'CSV y JSONL exportados'
                                print('[OK] Dataset sensores:', *(str(p) for p in paths.values()), sep='\n')
                        elif key == pygame.K_s:
                            self.sensors_visible = not self.sensors_visible
                        elif key == pygame.K_TAB:
                            self.selected_sensor_idx = (self.selected_sensor_idx + 1) % len(self.scene.sensor_positions)
                        elif key == pygame.K_h:
                            self.smoke_visible = not self.smoke_visible
                        elif key == pygame.K_d and hasattr(self, 'toggle_debug'):
                            self.toggle_debug()
                            self.camera.fit(tuple(area()))
                            scale_cache.clear()
                        elif key == pygame.K_f:
                            self.camera.fit(tuple(area()))
                            scale_cache.clear()
                        elif key == pygame.K_n:
                            self.labels = not self.labels
                        elif key == pygame.K_g:
                            self.grid = not self.grid
                        elif key == pygame.K_p:
                            self.accesses = not self.accesses
                        elif key in (pygame.K_EQUALS, pygame.K_KP_PLUS):
                            if hasattr(self, 'set_simulation_speed'):
                                try_action(lambda: self.set_simulation_speed(self.playback.speed_multiplier*1.25))
                            else:
                                self.turn_seconds = max(.06, self.turn_seconds/1.25)
                        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                            if hasattr(self, 'set_simulation_speed'):
                                try_action(lambda: self.set_simulation_speed(self.playback.speed_multiplier/1.25))
                            else:
                                self.turn_seconds = min(3.0, self.turn_seconds*1.25)
                    elif event.type == pygame.MOUSEWHEEL:
                        mx, my = pygame.mouse.get_pos()
                        if area().collidepoint(mx, my):
                            self.camera.zoom_at(mx, my, event.y)
                            scale_cache.clear()
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        if event.button == 3:
                            self.drag = area().collidepoint(event.pos)
                        elif event.button == 1 and area().collidepoint(event.pos):
                            if hasattr(self, 'handle_map_click'):
                                try_action(lambda: self.handle_map_click(event.pos, tuple(area())))
                            else:
                                gx = int((event.pos[0]-self.camera.offset_x)//self.camera.zoom)
                                gy = int((event.pos[1]-self.camera.offset_y)//self.camera.zoom)
                                if self._select_sensor_near(*event.pos):
                                    pass
                                elif self.scene.is_emergency and self.scene.info['fase'] in ('en_curso','pausado'):
                                    try_action(lambda: self.scene.ignite(gx, gy))
                    elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                        self.drag = False
                    elif event.type == pygame.MOUSEMOTION and self.drag:
                        self.camera.pan(*event.rel)

                if hasattr(self, 'advance_playback'):
                    if try_action(lambda: self.advance_playback(dt), mark_dirty=False):
                        overlays_dirty = True
                elif self.scene.info['fase'] == 'en_curso':
                    self.accumulator += dt
                    if self.accumulator >= self.turn_seconds:
                        try_action(self.scene.step)
                        self.accumulator = self.accumulator % self.turn_seconds
                else:
                    self.accumulator = 0

                if overlays_dirty:
                    smoke_surface = self._smoke_layer(pygame, self.scene, self.snapshot.width, self.snapshot.height)
                    fire_surface = self._fire_layer(pygame, self.scene, self.snapshot.width, self.snapshot.height)
                    overlays_dirty = False
                    scale_cache.clear()

                sw, sh = screen.get_size()
                rect = area()
                screen.fill(BACKGROUND)
                screen.set_clip(rect)
                size = (max(1, round(self.snapshot.width*self.camera.zoom)),
                        max(1, round(self.snapshot.height*self.camera.zoom)))
                if scale_cache.get('size') != size:
                    scale_cache.clear()
                    scale_cache['size'] = size
                    scale_cache['terrain'] = pygame.transform.scale(terrain_surface, size)
                    scale_cache['fire'] = pygame.transform.scale(fire_surface, size)
                    scale_cache['smoke'] = pygame.transform.scale(smoke_surface, size)
                sx, sy = self.camera.project(0, 0)
                screen.blit(scale_cache['terrain'], (sx, sy))
                screen.blit(scale_cache['fire'], (sx, sy))
                if self.smoke_visible:
                    screen.blit(scale_cache['smoke'], (sx, sy))

                # Rellenos simples por celda: azul dentro, verde fuera, rojo incapacitada.
                for person in self.scene.people:
                    px, py = self.camera.project(person.x+.5, person.y+.5)
                    if not rect.collidepoint(px, py):
                        continue
                    risk = (self.scene.exposure.records[person.person_id].level
                            if self.scene.exposure is not None else 'normal')
                    color = ((221, 72, 93) if risk == 'incapacitada' else
                             (58, 218, 151) if person.building_id is None else (70, 210, 242))
                    minimum_radius = getattr(self, 'person_marker_min_radius', 2)
                    pygame.draw.circle(screen, (15, 27, 43), (px, py), max(minimum_radius+getattr(self, "person_outline_extra", 0), int(self.camera.zoom*.48)))
                    pygame.draw.circle(screen, color, (px, py), max(minimum_radius, int(self.camera.zoom*.36)))
                    if risk == 'incapacitada' and self.camera.zoom >= 7:
                        r = 3
                        pygame.draw.line(screen, TEXT, (px-r, py-r), (px+r, py+r), 1)
                        pygame.draw.line(screen, TEXT, (px+r, py-r), (px-r, py+r), 1)

                if self.grid and self.camera.zoom >= getattr(self, 'grid_zoom_threshold', 8):
                    for x in range(self.snapshot.width+1):
                        ex, _ = self.camera.project(x, 0)
                        pygame.draw.line(screen, (123,143,160), (ex,rect.top), (ex,rect.bottom), 1)
                    for y in range(self.snapshot.height+1):
                        _, ey = self.camera.project(0, y)
                        pygame.draw.line(screen, (123,143,160), (rect.left,ey), (rect.right,ey), 1)
                if self.accesses:
                    for _, ax, ay in self.snapshot.entrances:
                        px, py = self.camera.project(ax+.5, ay+.5)
                        if rect.collidepoint(px, py):
                            pygame.draw.circle(screen, (251, 208, 92), (px, py), max(2, min(7, int(self.camera.zoom*.4))), 1)
                if self.labels and self.camera.zoom >= getattr(self, 'label_zoom_threshold', 4.3):
                    for name, (cx, cy) in self.snapshot.centers.items():
                        px, py = self.camera.project(cx, cy)
                        if rect.collidepoint(px, py):
                            words = font_label.render(name, True, TEXT)
                            tag = words.get_rect(center=(px,py))
                            pygame.draw.rect(screen,(21,40,59),tag.inflate(7,4),border_radius=3)
                            screen.blit(words,tag)
                self._draw_sensor_markers(pygame, screen, rect)
                screen.set_clip(None)
                pygame.draw.rect(screen, MUTED, rect, 1)
                self._draw_sidebar(pygame, screen, fonts, clock.get_fps())
                pygame.display.flip()
                if getattr(self, "screenshot_path", None):
                    pygame.image.save(screen, str(self.screenshot_path))
                frames += 1
                if smoke_test and frames >= 3:
                    running = False
            if smoke_test:
                print(f'[OK] Paso 14.4.4: arranque grafico de 3 fotogramas; modo={self.scene.mode}')
        finally:
            pygame.quit()
