"""Reutiliza la ventana existente; solo anade capas/estado del nuevo escenario."""
from __future__ import annotations

from .application import DisasterCommandCenterApp
from .mode_application import ModeSensorDisasterApp
from .sensor_application import SensorDisasterApp
from .functional_scene import FunctionalScene
from .presentation import HEADER_H, FOOTER_H, PANEL, TEXT, MUTED, rect_map

TURTLE_MESSAGE = "Ninguna tortuga saldrá lastimada durante esta simulación."


class FunctionalDisasterApp(ModeSensorDisasterApp):
    def __init__(self, snapshot, root, *, mode=None):
        DisasterCommandCenterApp.__init__(self, snapshot)
        self.scene = FunctionalScene(root, mode=mode)
        self.sensors_visible, self.smoke_visible = True, True
        self.selected_sensor_idx = 0
        self.turn_seconds, self.accumulator = .40, 0.0
        self.person_marker_min_radius = 1
        self.window_caption = "Disaster Command Center | Escenario detallado y zonas de reunion"
        self.click_help = "clic izquierdo selecciona foco antes de A; despues no genera focos"
        self.label_zoom_threshold = 1.4
        self.grid_zoom_threshold = 3
        self.message = "Clic: elige foco; A inicia alarma"

    def handle_map_click(self, position, map_rect):
        cell = self.camera.cell_at(*position, clip_rect=map_rect)
        if cell is None:
            return False
        if self.scene.center.phase == "preparado" and self.scene.is_emergency:
            self.scene.select_ignition(*cell)
            self.message = f"Foco seleccionado: {cell}; A inicia"
            return True
        # Tras la alarma solo permite inspeccionar sensores; nunca genera focos.
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
            self._meeting_font = pygame.font.SysFont("arial", 12, bold=True)
        if self.scene.is_emergency and self.scene.center.phase == "preparado":
            x, y = self.scene.center.ignition_cell
            px, py = self.camera.project(x+.5, y+.5)
            pygame.draw.circle(screen, (245, 120, 55), (px, py), 8, 2)
            pygame.draw.line(screen, (245, 120, 55), (px-11, py), (px+11, py), 1)
            pygame.draw.line(screen, (245, 120, 55), (px, py-11), (px, py+11), 1)
        for meeting in self.scene.center.areas:
            x, y, w, h = meeting.bounds
            px, py = self.camera.project(x, y)
            color = (90, 220, 151) if self.scene.center.router.safe[meeting.area_id] else (255, 125, 85)
            pygame.draw.rect(screen, color, (px, py, max(1, round(w*self.camera.zoom)),
                                           max(1, round(h*self.camera.zoom))), 2)
            screen.blit(self._meeting_font.render(meeting.area_id, True, (15, 45, 29)), (px+3, py+3))
        for name, level in self.scene.center.building_risk.levels.items():
            if level == "critical":
                cx, cy = self.snapshot.centers[name]
                point = self.camera.project(cx, cy)
                pygame.draw.circle(screen, (255, 150, 65), point, 11, 2)
        if self.scene.is_emergency:
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
        super()._draw_sensor_markers(pygame, screen, area)

    def _draw_sidebar(self, pygame, screen, fonts, fps):
        SensorDisasterApp._draw_sidebar(self, pygame, screen, fonts, fps)
        width, height = screen.get_size()
        left = rect_map(width, height)[2]
        small = fonts[2]
        pygame.draw.rect(screen, PANEL, (12, 44, min(950, width-20), 27))
        text = f"Detalle {self.snapshot.width}x{self.snapshot.height} | {len(self.scene.people)} alumnos | laboratorios violeta | R1-R8 reunion"
        screen.blit(small.render(text, True, MUTED), (19, 48))
        pygame.draw.rect(screen, PANEL, (left+5, HEADER_H+42, width-left-10, 23))
        x, y = self.scene.center.ignition_cell
        scenario = f"Escenario: emergencia | foco {x},{y}" if self.scene.is_emergency else "Escenario: normal"
        screen.blit(small.render(scenario, True, TEXT), (left+13, HEADER_H+45))
        meeting = self.scene.center.router.summary()
        lines = [f"En reunion / sin destino: {meeting['gathered']} / {meeting['unassigned']}",
                 f"Zonas disponibles: {sum(self.scene.center.router.safe.values())}/8 | Reasignaciones: {meeting['reassignments']}",
                 f"Viento: {self.scene.direction} | velocidad {self.scene.intensity:.2f} (0..1)"]
        y = height-FOOTER_H-77
        pygame.draw.rect(screen, PANEL, (left+5, y-3, width-left-10, 76))
        for text in lines:
            screen.blit(small.render(text, True, TEXT), (left+13, y))
            y += 23
        self._draw_footer(pygame, screen, fonts)

    def _draw_footer(self, pygame, screen, fonts):
        width, height = screen.get_size()
        left = rect_map(width, height)[2]
        pygame.draw.rect(screen, PANEL, (0, height-FOOTER_H, left, FOOTER_H))
        controls = "Clic foco antes de A | A alarma | ESPACIO pausa | R reinicia | V viento | [ ] velocidad | E exporta | ESC"
        for text, y in ((controls, height-42), (TURTLE_MESSAGE, height-22)):
            rendered = fonts[2].render(text, True, TEXT)
            if rendered.get_width() > left-26:
                rendered = pygame.transform.smoothscale(rendered, (max(1, left-26), rendered.get_height()))
            screen.blit(rendered, (13, y))
