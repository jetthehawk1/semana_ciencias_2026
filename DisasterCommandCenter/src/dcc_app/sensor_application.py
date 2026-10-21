"""Paso 14.4.3: nueva interfaz de sensores sobre el visor 14.4.2.

No reemplaza el visor previo ni los motores. Datos sinteticos, no fisicos.
"""
from __future__ import annotations

from .application import DisasterCommandCenterApp
from .presentation import BACKGROUND, COLORS, FOOTER_H, HEADER_H, MUTED, PANEL, TEXT, rect_map
from .sensor_scene import SensorLiveScene
from .live_application import LiveDisasterApp
from datetime import datetime


class SensorDisasterApp(LiveDisasterApp):
    def __init__(self, snapshot, root):
        super().__init__(snapshot, root)
        self.scene = SensorLiveScene(root)
        self.sensors_visible = True
        self.selected_sensor_idx = 0
        self.smoke_visible = True
        self.turn_seconds = 0.40  # solo ritmo de animacion, no tiempo de evacuacion
        self.accumulator = 0.0
        self.message = 'Listo: A inicia la alarma y el incendio en E30'

    @staticmethod
    def _smoke_layer(pygame, scene, width, height):
        layer = pygame.Surface((width, height), pygame.SRCALPHA)
        if scene.environment is None:
            return layer
        for y, row in enumerate(scene.environment.smoke.concentrations):
            for x, density in enumerate(row):
                if density > 0.007:
                    layer.set_at((x, y), (35, 41, 55, min(205, int(density*205) + 12)))
        return layer

    @staticmethod
    def _fire_layer(pygame, scene, width, height):
        layer = pygame.Surface((width, height), pygame.SRCALPHA)
        if scene.environment is None:
            return layer
        for x, y in scene.environment.fire.burned:
            layer.set_at((x, y), (70, 32, 38, 220))
        for x, y in scene.environment.fire.burning:
            layer.set_at((x, y), (250, 98, 37, 255))
        return layer

    def _draw_sidebar(self, pygame, screen, fonts, fps):
        w, h = screen.get_size()
        left = rect_map(w, h)[2]
        pygame.draw.rect(screen, PANEL, (0, 0, w, HEADER_H))
        pygame.draw.rect(screen, PANEL, (left, HEADER_H, w-left, h-HEADER_H))
        pygame.draw.rect(screen, PANEL, (0, h-FOOTER_H, w, FOOTER_H))
        big, med, small = fonts
        screen.blit(big.render('DISASTER COMMAND CENTER', True, TEXT), (17, 12))
        screen.blit(small.render('Paso 14.4.3 | Personas + fuego + humo + viento + 12 sensores sinteticos', True, MUTED), (19, 48))

        def line(value, yy, *, color=TEXT, font=small):
            if yy < h - FOOTER_H - 9:
                screen.blit(font.render(str(value), True, color), (left + 13, yy))

        info = self.scene.info
        stats = self.scene.sensor_stats
        line('CENTRO DE CONTROL', HEADER_H + 14, font=med)
        y = HEADER_H + 45
        rows = [
            ('Escenario', 'E30 + incendio' if self.scene.is_emergency else 'Normal (sensores sin lectura)'),
            ('Fase / turno', f"{info['fase']} / {info['turnos']}"),
            ('Personas dentro / fuera', f"{info['dentro']} / {info['salieron']}"),
            ('Personas esperando', str(info['esperando'])),
        ]
        if self.scene.is_emergency:
            fire, smoke, risk = info['fuego'], info['humo'], info['riesgo']
            rows += [
                ('Fuego activo / quemado', f"{fire['burning']} / {fire['burned']}"),
                ('Celdas con humo', str(smoke['smoky_cells'])),
                ('Incapacitadas (modelo)', str(risk['incapacitada'])),
                ('Viento hacia / intensidad', f'{self.scene.direction} / {self.scene.intensity:.2f}'),
            ]
        for label, value in rows:
            line(f'{label}: {value}', y)
            y += 23

        y += 7
        line('SENSORES VIRTUALES', y, font=med)
        y += 27
        line(f"Registrados: {stats['installed']} | Alarmas: {stats['alarms']}", y)
        y += 22
        line(f"Lecturas acumuladas: {stats['total_records']}", y)
        y += 22
        if stats['active']:
            line(f"Turno muestreado: {stats['last_turn']}", y)
            y += 22
            line(f"Temp maxima ficticia: {stats['max_temperature_c']:.1f} C", y)
            y += 22
            line(f"Humo maximo: {stats['max_smoke_index']:.3f} / 1.0", y)
        else:
            line('Sin muestras (A inicia en emergencia)', y, color=MUTED)
        y += 31
        spec = self.scene.sensor_positions[self.selected_sensor_idx]
        selected = next((r for r in self.scene.current_readings if r['sensor_id'] == spec['sensor_id']), None)
        line('SENSOR SELECCIONADO (TAB)', y, font=med)
        y += 25
        line(f"{spec['sensor_id']} | ({spec['x']},{spec['y']})", y)
        y += 23
        if selected is None:
            line('Sin lectura actual', y, color=MUTED)
        else:
            line(f"{selected['temperature_c']:.1f} C sim. | humo {selected['smoke_index']:.3f}", y)
            y += 23
            line('ALERTA SIMULADA' if selected['alarm'] else 'Sin alarma', y,
                 color=(255, 149, 85) if selected['alarm'] else (83, 216, 186))

        screen.blit(small.render('A alarma | ESPACIO pausa | . turno | R reiniciar | T escenario | E exportar | S sensores', True, TEXT), (13, h-40))
        screen.blit(small.render('TAB sensor | V viento | [ ] intensidad | H humo | F mapa | N/G/P capas | ESC', True, TEXT), (13, h-22))
        screen.blit(small.render(f'{self.message[:31]} | {fps:.0f} FPS', True, MUTED), (left + 9, h-23))

    def _draw_sensor_markers(self, pygame, screen, area):
        if not self.sensors_visible:
            return
        alarms = {r['sensor_id'] for r in self.scene.current_readings if r['alarm']}
        for i, sensor in enumerate(self.scene.sensor_positions):
            sx, sy = self.camera.project(sensor['x']+.5, sensor['y']+.5)
            if not area.collidepoint(sx, sy):
                continue
            selected = i == self.selected_sensor_idx
            color = ((253, 146, 77) if sensor['sensor_id'] in alarms else (68, 224, 206))
            radius = max(4, min(9, round(self.camera.zoom*.47)))
            pygame.draw.circle(screen, (18, 33, 46), (sx,sy), radius+2)
            pygame.draw.circle(screen, color, (sx,sy), radius)
            if selected:
                pygame.draw.circle(screen, (255, 251, 158), (sx,sy), radius+4, 2)

    def _select_sensor_near(self, x, y):
        if not self.sensors_visible:
            return False
        radius = max(9, min(15, round(self.camera.zoom*.8)))
        closest = None
        for i, spec in enumerate(self.scene.sensor_positions):
            px, py = self.camera.project(spec['x']+.5, spec['y']+.5)
            sq = (x-px)**2 + (y-py)**2
            if sq <= radius**2 and (closest is None or sq < closest[0]):
                closest = (sq, i)
        if closest is None:
            return False
        self.selected_sensor_idx = closest[1]
        self.message = 'Sensor seleccionado: ' + self.scene.sensor_positions[self.selected_sensor_idx]['sensor_id']
        return True

    def run(self, *, smoke_test=False):
        import pygame
        pygame.init()
        try:
            screen = pygame.display.set_mode((1320, 830), pygame.RESIZABLE)
            pygame.display.set_caption('Disaster Command Center | Sensores y estadisticas 14.4.3')
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
                return pygame.Rect(*rect_map(*screen.get_size()))

            def try_action(fn):
                nonlocal overlays_dirty
                try:
                    value = fn()
                    overlays_dirty = True
                    return value
                except (ValueError, RuntimeError) as exc:
                    self.message = str(exc)
                    return None

            self.camera.fit(tuple(area()))
            print(f'[OK] App integrada: {self.snapshot.width}x{self.snapshot.height}; '
                  f'personas={len(self.scene.people)}; escenario={self.scene.kind}; '
                  'modo=original (selector: paso 14.4.4); sensores=12.')
            print('A alarma; ESPACIO pausa; . turno; R reinicia; T cambia escenario antes de A; '
                  'V viento; [ ] intensidad; H humo; clic izquierdo agrega foco tras alarma; '
                  'E exportar; S sensores; TAB seleccionar; F encuadrar; N etiquetas; G cuadricula; P accesos; ESC cerrar.')
            frames = 0
            running = True
            while running:
                dt = min(clock.tick(45)/1000.0, 0.15)
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
                        elif key == pygame.K_v:
                            val = try_action(self.scene.cycle_wind)
                            if val:
                                self.message = 'Viento hacia ' + val
                        elif key in (pygame.K_RIGHTBRACKET, pygame.K_LEFTBRACKET):
                            delta = 0.1 if key == pygame.K_RIGHTBRACKET else -0.1
                            try_action(lambda: self.scene.adjust_wind(delta))
                        elif key == pygame.K_e:
                            from pathlib import Path
                            output = (self.scene.root / 'exports' / 'sensores_paso_14_4_3'
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
                            self.turn_seconds = max(.06, self.turn_seconds/1.25)
                        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
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

                if self.scene.info['fase'] == 'en_curso':
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
                    pygame.draw.circle(screen, (15, 27, 43), (px, py), max(2, int(self.camera.zoom*.48)))
                    pygame.draw.circle(screen, color, (px, py), max(2, int(self.camera.zoom*.36)))
                    if risk == 'incapacitada' and self.camera.zoom >= 7:
                        r = 3
                        pygame.draw.line(screen, TEXT, (px-r, py-r), (px+r, py+r), 1)
                        pygame.draw.line(screen, TEXT, (px+r, py-r), (px-r, py+r), 1)

                if self.grid and self.camera.zoom >= 8:
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
                if self.labels and self.camera.zoom >= 4.3:
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
                frames += 1
                if smoke_test and frames >= 3:
                    running = False
            if smoke_test:
                print('[OK] Paso 14.4.3: arranque grafico de 3 fotogramas')
        finally:
            pygame.quit()
