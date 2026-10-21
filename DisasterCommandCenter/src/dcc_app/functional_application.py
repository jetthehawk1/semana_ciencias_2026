"""Reutiliza la ventana existente; solo anade capas/estado del nuevo escenario."""
from __future__ import annotations

from .application import DisasterCommandCenterApp
from .mode_application import ModeSensorDisasterApp
from .sensor_application import SensorDisasterApp
from .functional_scene import FunctionalScene
from .playback import PlaybackClock
from .presentation import HEADER_H, FOOTER_H, PANEL, TEXT, MUTED, rect_map

from .presentation_view import TURTLE_MESSAGE, ZONE_LABELS, CONTROLS, PresentationMessages, presentation_data, student_lines, debug_student_data


class FunctionalDisasterApp(ModeSensorDisasterApp):
    def __init__(self, snapshot, root, *, mode=None, evacuation_mode=None):
        DisasterCommandCenterApp.__init__(self, snapshot)
        self.scene = FunctionalScene(root, mode=mode, evacuation_mode=evacuation_mode)
        self.sensors_visible, self.smoke_visible = True, True
        self.selected_sensor_idx = 0
        self.playback = PlaybackClock(self.scene.center.config["simulation_playback"])
        self.turn_seconds, self.accumulator = self.playback.interval_seconds, 0.0
        self.person_marker_min_radius = 1
        self.window_caption = "Disaster Command Center | Escenario detallado y zonas de reunion"
        self.click_help = "clic izquierdo selecciona foco antes de A; despues no genera focos"
        self.label_zoom_threshold = 1.4
        self.grid_zoom_threshold = 3
        self.message = "Clic: elige foco; A inicia alarma"
        self.debug_risk = False
        self.selected_person = None
        self.person_outline_extra = 1
        self.presentation_messages = PresentationMessages(self.scene.center.config["presentation"])
        self._presentation_key = None

    def map_area(self, width, height):
        return rect_map(width, height) if self.debug_risk else (0, 136, width, max(1, height-206))

    def toggle_debug(self):
        self.debug_risk = not self.debug_risk
        return self.debug_risk

    def set_simulation_speed(self, multiplier):
        """API para futuros sliders: solo cambia tiempo real entre turnos."""
        self.turn_seconds = self.playback.set_speed(multiplier)
        self.accumulator = 0.0
        return self.turn_seconds

    def advance_playback(self, elapsed):
        if self.scene.center.phase != "en_curso":
            self.accumulator = 0.0
            return 0
        count, self.accumulator = self.playback.due_turns(self.accumulator+elapsed)
        for _ in range(count):
            self.scene.step()
        return count

    def handle_map_click(self, position, map_rect):
        cell = self.camera.cell_at(*position, clip_rect=map_rect)
        if cell is None:
            return False
        if self.scene.center.phase == "preparado" and self.scene.is_emergency:
            self.scene.select_ignition(*cell)
            self.message = f"Foco seleccionado: {cell}; A inicia"
            return True
        # Inspection uses the same camera conversion as ignition, including pan.
        nearest = min(self.scene.people, key=lambda p:(p.x-cell[0])**2+(p.y-cell[1])**2)
        radius = max(1.5, 7/self.camera.zoom)
        if (nearest.x-cell[0])**2+(nearest.y-cell[1])**2 <= radius**2:
            self.selected_person = (self.scene.session, nearest.person_id)
            self.message = 'Alumno '+nearest.person_id+' seleccionado'
            return False
        self._select_sensor_near(*position)
        return False

    def _map_surface(self, pygame, snapshot):
        surface = DisasterCommandCenterApp._map_surface(pygame, snapshot)
        for y, row in enumerate(snapshot.owners):
            for x, name in enumerate(row):
                if name and self.scene.center.building_risk.properties[name]["laboratory"]:
                    surface.set_at((x, y), (110, 107, 146))
        for area in self.scene.center.areas:
            for point in area.cells:
                surface.set_at(point, (181, 205, 181))
        return surface

    @staticmethod
    def _smoke_layer(pygame, scene, width, height):
        layer = pygame.Surface((width, height), pygame.SRCALPHA)
        if scene.environment is not None:
            for y, row in enumerate(scene.environment.smoke.concentrations):
                for x, amount in enumerate(row):
                    if amount > 0:
                        layer.set_at((x, y), (22, 25, 32, min(225, round(amount*225))))
        return layer

    def _draw_sensor_markers(self, pygame, screen, area):
        if not hasattr(self, "_meeting_font"):
            self._meeting_font = pygame.font.SysFont("arial", 16, bold=True)
        if self.debug_risk:
            import numpy as np
            risk = self.scene.center.risk_field
            key = (self.scene.session, risk.turn, self.camera.zoom)
            if getattr(self, '_debug_key', None) != key:
                layer = pygame.Surface((risk.width, risk.height), pygame.SRCALPHA)
                colors = pygame.surfarray.pixels3d(layer)
                colors[:,:,0] = 235; colors[:,:,1] = 65; colors[:,:,2] = 30
                del colors
                alpha = pygame.surfarray.pixels_alpha(layer)
                alpha[:,:] = np.minimum(120, risk.costs.T*2).astype(np.uint8)
                del alpha
                self._debug_layer = pygame.transform.scale(layer,
                    (max(1,round(risk.width*self.camera.zoom)),max(1,round(risk.height*self.camera.zoom))))
                self._debug_key = key
            screen.blit(self._debug_layer,self.camera.project(0,0))
            threat = self.scene.center.next_turn_threat
            if threat is not None:
                ys, xs = np.nonzero(threat.frontier)
                for x, y in zip(xs, ys):
                    px, py = self.camera.project(x, y)
                    pygame.draw.rect(screen, (255, 220, 75), (px, py, max(1, round(self.camera.zoom)), max(1, round(self.camera.zoom))), 1)
            screen.blit(self._meeting_font.render('D: riesgo/humo previsto (rojo); frente preventivo (amarillo)',True,(240,220,180)),(area.x+8,area.bottom-22))
        if self.scene.is_emergency and self.scene.center.phase == "preparado":
            x, y = self.scene.center.ignition_cell
            px, py = self.camera.project(x+.5, y+.5)
            pygame.draw.circle(screen, (245, 120, 55), (px, py), 8, 2)
            pygame.draw.line(screen, (245, 120, 55), (px-11, py), (px+11, py), 1)
            pygame.draw.line(screen, (245, 120, 55), (px, py-11), (px, py+11), 1)
        for meeting in self.scene.center.areas:
            x, y, w, h = meeting.bounds
            px, py = self.camera.project(x, y)
            state = self.scene.center.router.area_policy.states[meeting.area_id]
            color = {"SAFE": (90, 220, 151), "CAUTION": (215, 185, 85),
                     "AVOID": (255, 150, 85), "CLOSED": (245, 95, 85)}[state]
            pygame.draw.rect(screen, color, (px, py, max(1, round(w*self.camera.zoom)),
                                           max(1, round(h*self.camera.zoom))), 2)
            screen.blit(self._meeting_font.render(f"{meeting.area_id} {state if self.debug_risk else ZONE_LABELS[state]}", True, (15, 45, 29)), (px+3, py+3))
        for name, level in self.scene.center.building_risk.levels.items():
            if level == "critical":
                cx, cy = self.snapshot.centers[name]
                point = self.camera.project(cx, cy)
                pygame.draw.circle(screen, (255, 150, 65), point, 11, 2)
        if self.scene.is_emergency and self.debug_risk:
            dx, dy = self.scene.environment.wind.vector
            speed = self.scene.center.wind_history.state.speed
            start = (area.right-62, area.top+32)
            length = 30*speed
            tip = (round(start[0]+dx*length), round(start[1]+dy*length))
            if speed > 0:
                color = (80, 120, 155)
                pygame.draw.line(screen, color, start, tip, 2)
                pygame.draw.polygon(screen, color, [tip,
                    (round(tip[0]-dx*8-dy*4), round(tip[1]-dy*8+dx*4)),
                    (round(tip[0]-dx*8+dy*4), round(tip[1]-dy*8-dx*4))])
            screen.blit(self._meeting_font.render(f"{self.scene.direction} {speed:.2f}", True, (35, 65, 85)),
                        (area.right-91, area.top+58))
        if self.debug_risk:
            super()._draw_sensor_markers(pygame, screen, area)
        if self.selected_person and self.selected_person[0] == self.scene.session:
            pid = self.selected_person[1]
            person = self.scene.center.manager.get_person(pid)
            policy = self.scene.center.decision_policy
            if person is not None:
                point = self.camera.project(person.x+.5,person.y+.5)
                pygame.draw.circle(screen,(255,225,70),point,7,2)
                d = policy.diagnostics.get(pid,{}) if policy else debug_student_data(self.scene.center, pid)
                def eta(key):
                    value = d.get(key,float('inf'))
                    if value is None:
                        return 'sin cálculo personal'
                    return f'{value:.1f}' if abs(value)<1e8 else 'fuera horizonte'
                router = self.scene.center.router
                assignment = router.assignments.get(pid)
                priority_label = f"{d.get('priority',0):.0f}" if policy else '—'
                lines = [f"{pid} | {d.get('state',self.scene.center.tracker.records[pid].level)}",
                    f"Destino: {assignment[0] if assignment else 'sin asignar'} | margen {eta('safety_margin')}",
                    f"ETA fuego: {eta('fire_eta')} | humo: {eta('smoke_eta')}",
                    f"ETA dosis: {eta('toxic_dose_eta')} | prioridad exterior: {priority_label}",
                    f"Motivo: {router.person_reasons.get(pid,router.pending_reasons.get(pid,'ruta vigente'))}"]
                if not self.debug_risk:
                    lines = student_lines(self.scene.center, pid)
                box=pygame.Surface((min(370,area.width-16),112),pygame.SRCALPHA)
                box.fill((20,32,48,230));screen.blit(box,(area.x+8,area.y+8))
                if not hasattr(self, "_inspection_font"):
                    self._inspection_font = pygame.font.SysFont("arial", 12)
                card_font = self._inspection_font if self.debug_risk else self._meeting_font
                for i,text in enumerate(lines):
                    screen.blit(card_font.render(text,True,(235,240,245)),(area.x+14,area.y+14+i*20))

    def _draw_sidebar(self, pygame, screen, fonts, fps):
        if not self.debug_risk:
            self._draw_presentation(pygame, screen)
            return
        SensorDisasterApp._draw_sidebar(self, pygame, screen, fonts, fps)
        width, height = screen.get_size()
        left = rect_map(width, height)[2]
        small = fonts[2]
        pygame.draw.rect(screen, PANEL, (12, 44, min(950, width-20), 27))
        mode = 'INTELIGENTE' if self.scene.center.decision_policy else 'TRADICIONAL'
        text = f"Modo: {mode} | {self.snapshot.width}x{self.snapshot.height} | {len(self.scene.people)} alumnos | R1-R8 | x{self.playback.speed_multiplier:g}"
        screen.blit(small.render(text, True, MUTED), (19, 48))
        pygame.draw.rect(screen, PANEL, (left+5, HEADER_H+42, width-left-10, 23))
        x, y = self.scene.center.ignition_cell
        scenario = f"Escenario: emergencia | foco {x},{y}" if self.scene.is_emergency else "Escenario: normal"
        screen.blit(small.render(scenario, True, TEXT), (left+13, HEADER_H+45))
        meeting = self.scene.center.router.summary()
        forecast = self.scene.center.predicted_wind
        wind_line = (f"Viento {self.scene.direction} {self.scene.intensity:.2f} | prev. {forecast.direction} {forecast.speed:.2f} [{forecast.method[0].upper()}]"
                     if forecast else f"Viento {self.scene.direction} {self.scene.intensity:.2f} | sin muestras")
        policy = self.scene.center.decision_policy
        counts = self.scene.center.summary()['evacuation_states']
        forecast_label = ('Ridge' if forecast and forecast.method == 'ridge' else 'persistencia')
        lines = [f"Reunion / sin destino: {meeting['gathered']} / {meeting['unassigned']}",
                 f"Replanes: {meeting['replanned_routes']} | Prev.: {meeting['preventive_reassignments']}",
                 f"Espera insegura: {counts.get('WAITING_UNSAFE', 0)} | Zonas evitadas: {policy.avoided_destinations if policy else 0}",
                 f"Prediccion: {forecast_label} | {self.scene.direction} {self.scene.intensity:.2f}"]
        score_key = (self.scene.center.run_id, self.scene.environment.fire.turn)
        if getattr(self, '_score_key', None) != score_key:
            self._debug_score = self.scene.center.metrics.result(self.scene.center).get('SafetyScore', 0.)
            self._score_key = score_key
        lines.append(f"SafetyScore didáctico: {self._debug_score:.1f}")
        if policy and policy.events:
            lines.append(policy.events[-1]['message'])
        self.visible_debug_text = lines[:]
        y = height-FOOTER_H-(len(lines)*21+5)
        pygame.draw.rect(screen, PANEL, (left+5, y-3, width-left-10, len(lines)*21+6))
        for text in lines:
            screen.blit(small.render(text, True, TEXT), (left+13, y))
            y += 21
        self._draw_footer(pygame, screen, fonts)

    def _draw_presentation(self, pygame, screen):
        if not hasattr(self, '_public_fonts'):
            self._public_fonts = (pygame.font.SysFont('arial', 25, bold=True),
                                  pygame.font.SysFont('arial', 21, bold=True),
                                  pygame.font.SysFont('arial', 18))
        title, label, small = self._public_fonts
        width, height = screen.get_size()
        center = self.scene.center
        key = (center.run_id, center.environment.fire.turn, center.phase, center.direction, center.intensity)
        if self._presentation_key != key:
            self._public_data = presentation_data(center)
            self._presentation_key = key
        data = self._public_data
        pygame.draw.rect(screen, PANEL, (0, 0, width, 136))
        pygame.draw.rect(screen, PANEL, (0, height-70, width, 70))
        self.visible_presentation_text = []

        def text(value, x, y, font=label, color=TEXT):
            self.visible_presentation_text.append(str(value))
            screen.blit(font.render(str(value), True, color), (x, y))

        text('Disaster Command Center', 16, 8, title)
        mode_color = (104, 239, 184) if data['mode'] == 'INTELIGENTE' else (173, 202, 244)
        text('MODO '+data['mode'], 440, 8, title, mode_color)
        text('VIENTO: '+data['wind'], 920, 8)
        # Hand-drawn arrow avoids missing glyphs in projector fonts.
        dx, dy = center.environment.wind.vector
        start = (width-54, 28); tip = (round(start[0]+dx*24), round(start[1]+dy*24))
        if center.intensity > 0:
            pygame.draw.line(screen, (150, 220, 255), start, tip, 4)
            pygame.draw.polygon(screen, (150, 220, 255), [tip,
                (round(tip[0]-dx*10-dy*5), round(tip[1]-dy*10+dx*5)),
                (round(tip[0]-dx*10+dy*5), round(tip[1]-dy*10-dx*5))])
        for x, heading, value, color in [
            (16, 'EN ZONA SEGURA', data['safe'], (104, 239, 184)),
            (275, 'EVACUANDO', data['evacuating'], TEXT),
            (535, 'DENTRO', data['inside'], TEXT),
            (795, 'INCAPACITADOS', data['incapacitated'], (255, 189, 151))]:
            text(f'{heading}: {value}', x, 53, label, color)
        text(f"Zonas: {data['available']} / {data['total_areas']} disponibles", 1050, 55, small)
        text('INCENDIO: '+data['fire'], 16, 97)
        text('HUMO: '+data['smoke'], 275, 97)
        text(f"Velocidad del viento: {data['speed']} ({center.intensity:.1f})", 535, 97, small)
        status = {'preparado': 'Elige el foco con un clic; A inicia',
                  'en_curso': 'EVACUACIÓN EN CURSO', 'pausado': 'SIMULACIÓN EN PAUSA',
                  'completado': 'SIMULACIÓN TERMINADA'}[center.phase]
        text(status, 960, 99, small)
        text(CONTROLS, 16, height-61, small)
        text(TURTLE_MESSAGE, 16, height-30, label, (204, 231, 208))
        messages = self.presentation_messages.observe(center)
        for i, message in enumerate(messages):
            rendered = small.render(message, True, TEXT)
            box = pygame.Rect(14, height-112-32*(len(messages)-1-i), rendered.get_width()+22, 29)
            pygame.draw.rect(screen, (28, 47, 61), box, border_radius=5)
            screen.blit(rendered, (box.x+11, box.y+3))
            self.visible_presentation_text.append(message)
        cfg = center.config['presentation']
        if center.phase == 'completado' or (center.phase == 'pausado' and center.environment.fire.turn >= cfg['episode_summary_turn']):
            lines = ['SIMULACIÓN TERMINADA' if center.phase == 'completado' else 'RESUMEN — SIMULACIÓN EN PAUSA',
                     f"Alumnos en zona segura: {data['safe']}", f"Incapacitados: {data['incapacitated']}",
                     f'Rutas cambiadas: {center.router.replanned_routes}',
                     f"Cambios de zona: {sum(e['from'] in center.router.areas and e['to'] in center.router.areas for e in center.router.destination_changes)}"]
            box = pygame.Rect(width//2-270, height//2-98, 540, 196)
            pygame.draw.rect(screen, PANEL, box, border_radius=10)
            pygame.draw.rect(screen, (120, 200, 170), box, 2, border_radius=10)
            for i, line in enumerate(lines):
                text(line, box.x+20, box.y+16+34*i, small if i == 0 else label)

    def _draw_footer(self, pygame, screen, fonts):
        width, height = screen.get_size()
        left = rect_map(width, height)[2]
        pygame.draw.rect(screen, PANEL, (0, height-FOOTER_H, left, FOOTER_H))
        controls = "Clic: foco antes de A / alumno despues | D riesgo | A alarma | ESPACIO pausa | R reinicia | V viento | [ ] viento | E exporta | ESC"
        for text, y in ((controls, height-42), (TURTLE_MESSAGE, height-22)):
            rendered = fonts[2].render(text, True, TEXT)
            if rendered.get_width() > left-26:
                rendered = pygame.transform.smoothscale(rendered, (max(1, left-26), rendered.get_height()))
            screen.blit(rendered, (13, y))
