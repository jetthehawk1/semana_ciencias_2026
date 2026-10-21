"""Render real SDL frames at 1320x830 and verify D changes visualization only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT)]


def render(turns=40, output=None):
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    import pygame
    from dcc_app.functional_application import FunctionalDisasterApp
    from dcc_app.model import load_campus
    from tools.compare_evacuation_modes import physical_digest
    from tools.compare_evacuation_modes_v2 import input_fingerprint
    output = Path(output or ROOT/'reports/septima_fase')
    output.mkdir(parents=True, exist_ok=True)
    assets = ROOT/'data/functional'
    app = FunctionalDisasterApp(load_campus(assets/'campus.json', assets/'building_entrances.json'), ROOT, mode='optimizado')
    app.scene.start()
    app.presentation_messages.observe(app.scene.center)
    for _ in range(turns):
        app.scene.step()
        app.presentation_messages.observe(app.scene.center)
    app.scene.center.toggle_pause()
    before = physical_digest(app.scene.center), [p.position for p in app.scene.people]
    app.screenshot_path = output/'presentation.png'
    app.run(smoke_test=True)
    public_text = app.visible_presentation_text[:]
    scene = app.scene
    # run() owns SDL shutdown. Fresh visual objects avoid reusing font handles
    # after pygame.quit(); the paused simulation instance is shared read-only.
    app = FunctionalDisasterApp(app.snapshot, ROOT, mode='optimizado')
    app.scene = scene
    app.camera.fit(app.map_area(1320, 830))
    person = next(p for p in scene.people if p.building_id is not None)
    app.handle_map_click(app.camera.project(person.x+.5, person.y+.5), app.map_area(1320, 830))
    frame_modes = []
    original_flip = pygame.display.flip

    def capture_and_press_D():
        original_flip()
        index = len(frame_modes)
        name = ['presentation_student.png', 'debug.png', 'presentation_return.png'][index]
        pygame.image.save(pygame.display.get_surface(), str(output/name))
        frame_modes.append(app.debug_risk)
        if index < 2:
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))

    # Actual key events pass through the real loop, in ONE SDL session.
    with patch.object(pygame.display, 'flip', side_effect=capture_and_press_D):
        app.run(smoke_test=True)
    assert frame_modes == [False, True, False]
    assert not app.debug_risk
    assert before == (physical_digest(app.scene.center), [p.position for p in app.scene.people])
    report = dict(resolution=[1320, 830], turn=turns, source_hash=input_fingerprint(),
                  real_keyboard_D_roundtrip=True, unchanged_physics_and_positions=True,
                  visible_text=public_text, population=len(app.scene.people),
                  screenshots=['presentation.png', 'presentation_student.png', 'debug.png', 'presentation_return.png'])
    (output/'visual_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--turns', type=int, default=40)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.turns < 0:
        parser.error('turns must be nonnegative')
    render(args.turns, args.output_dir)
