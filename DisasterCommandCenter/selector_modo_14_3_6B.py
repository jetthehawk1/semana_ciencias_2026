"""Selector OPT-IN de motores de evacuacion. NO reemplaza modulos anteriores.

Modo por defecto: original. Solo crear_centro(..., modo=None) respeta la
configuracion; visores antiguos no usan este selector automaticamente.
Cambiar de modo implica crear una NUEVA simulacion (reset de escenario).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CONFIG = ROOT / 'data' / 'modo_ejecucion_14_3_6B.json'
FORMATO = 'DCC-modo-v1'
MODOS = ('original', 'optimizado')


def leer_modo(config: Path | None = None) -> str:
    """Original cuando no hay config. Ante config corrupta: fallar cerrado."""
    path = Path(config) if config is not None else CONFIG
    if path.is_symlink():
        raise RuntimeError('La configuracion no puede ser un enlace simbolico.')
    if not path.exists():
        return 'original'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f'Configuracion invalida: {path}') from exc
    if (not isinstance(value, dict) or value.get('formato') != FORMATO
            or value.get('modo') not in MODOS):
        raise RuntimeError('Configuracion de modo no compatible o alterada.')
    return value['modo']


def crear_centro(tipo: str, campus: str | Path, accesos: str | Path,
                 ocupacion: str | Path, *, modo: str | None = None,
                 configuracion: Path | None = None, **kwargs):
    """Fabrica por INSTANCIA; no altera importaciones globales ni clases.

    tipo: 'normal' o 'emergencia'. Para emergencia se permiten argumentos
    como ignition, direction, intensity, seed. Cambiar modo en marcha NO
    migra el estado; crear otra instancia desde sus archivos y semilla.
    """
    chosen = leer_modo(configuracion) if modo is None else modo
    if chosen not in MODOS:
        raise ValueError('Modo invalido: usa original u optimizado.')
    if tipo not in ('normal', 'emergencia'):
        raise ValueError('Tipo invalido: usa normal o emergencia.')
    if tipo == 'normal' and kwargs:
        raise ValueError('Opciones de incendio solo disponibles para emergencia.')
    if chosen == 'original':
        if tipo == 'normal':
            from simulation.evacuation_control import EvacuationControlCenter as Center
        else:
            from simulation.hazard_impact import FireEvacuationControlCenter as Center
    else:
        try:
            if tipo == 'normal':
                from adaptador_indice_14_3_5 import IndexedEvacuationControlCenter as Center
            else:
                from adaptador_indice_14_3_5 import IndexedFireEvacuationControlCenter as Center
        except ImportError as exc:
            raise RuntimeError('Falta el prototipo opt-in del Paso 14.3.5.') from exc
    return Center(campus, accesos, ocupacion, **kwargs)
