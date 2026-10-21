"""Paso 14.4.2: visor nuevo sobre la estructura 14.4.1, sin reemplazarla.

Capas: mapa base, fuego/humo, personas, entradas y etiquetas; panel de datos.
No incluye sensores ni selector optimizado (pasos 14.4.3 y 14.4.4).
"""
from __future__ import annotations

from .application import DisasterCommandCenterApp
from .presentation import BACKGROUND, COLORS, FOOTER_H, HEADER_H, MUTED, PANEL, TEXT, rect_map
from .live_scene import LiveScene


class LiveDisasterApp(DisasterCommandCenterApp):
    def __init__(self, snapshot, root):
        super().__init__(snapshot)
        self.scene = LiveScene(root)
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
        font_big, med, small = fonts

        def line(msg, y, *, color=TEXT, font=small):
            if y <= h-FOOTER_H-5:
                screen.blit(font.render(str(msg), True, color), (left+14, y))

        screen.blit(font_big.render('DISASTER COMMAND CENTER', True, TEXT), (17, 12))
        screen.blit(small.render('Paso 14.4.2  |  Personas + incendio + humo + viento  |  Modelo didactico', True, MUTED), (19, 48))
        info = self.scene.info
        line('CENTRO DE CONTROL', HEADER_H + 17, font=med)
        y = HEADER_H + 60
        scenario = 'EMERGENCIA EN E30' if self.scene.is_emergency else 'EVACUACION NORMAL'
        rows = [
            ('Escenario', scenario),
            ('Fase', info['fase'].upper()),
            ('Turnos', str(info['turnos'])),
            ('Personas', str(info['inicial'])),
            ('Dentro', str(info['dentro'])),
            ('Cruzaron las puertas', str(info['salieron'])),
            ('Esperando', str(info['esperando'])),
        ]
        if self.scene.is_emergency:
            fire = info['fuego']
            smoke = info['humo']
            risk = info['riesgo']
            rows += [
                ('Fuego activo', str(fire['burning'])),
                ('Celdas quemadas', str(fire['burned'])),
                ('Celdas con humo', str(smoke['smoky_cells'])),
                ('Riesgo elevado', str(risk['alerta'] + risk['ralentizada'])),
                ('Incapacitadas (modelo)', str(risk['incapacitada'])),
                ('Viento hacia', f'{self.scene.direction} / {self.scene.intensity:.2f}'),
            ]
        for title, value in rows:
            line(title + ':', y, color=MUTED)
            line(value, y+17, font=med)
            y += 41
        screen.blit(small.render('A alarma | ESPACIO pausa | . turno | R reiniciar | T escenario', True, TEXT), (13, h-40))
        screen.blit(small.render('V viento | [ ] intensidad | H humo | F encuadrar | rueda zoom | ESC salir', True, TEXT), (13, h-22))
        # Evitar superposicion con el mapa en la barra de informacion.
        msg = self.message[:44]
        screen.blit(small.render(f'{msg}  |  {fps:.0f} FPS', True, MUTED), (left+9, h-23))

    def run(self, *, smoke_test=False):
        import pygame
        pygame.init()
        try:
            screen = pygame.display.set_mode((1320, 830), pygame.RESIZABLE)
            pygame.display.set_caption('Disaster Command Center | Simulacion integrada 14.4.2')
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
                  'modo=original (selector: paso 14.4.4).')
            print('A alarma; ESPACIO pausa; . turno; R reinicia; T cambia escenario antes de A; '
                  'V viento; [ ] intensidad; H humo; clic izquierdo agrega foco tras alarma; '
                  'F encuadrar; N etiquetas; G cuadricula; P accesos; ESC cerrar.')
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
                            self.message = 'Escenario reiniciado; presiona A'
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
                            if self.scene.is_emergency and self.scene.info['fase'] in ('en_curso','pausado'):
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
                screen.set_clip(None)
                pygame.draw.rect(screen, MUTED, rect, 1)
                self._draw_sidebar(pygame, screen, fonts, clock.get_fps())
                pygame.display.flip()
                frames += 1
                if smoke_test and frames >= 3:
                    running = False
            if smoke_test:
                print('[OK] Paso 14.4.2: arranque grafico de 3 fotogramas')
        finally:
            pygame.quit()
