"""Dose budgets in simulation turns, not medical or toxicological predictions."""
from __future__ import annotations

import math


def toxic_dose_eta(exposure, current_smoke, predicted_smoke, config, *, dose_limit=2.75):
    if exposure is None:
        return math.inf
    if exposure.level == 'incapacitada':
        return 0.
    remaining = max(0., dose_limit-exposure.dose)
    # Plume is a heuristic, not a forecast concentration. Only its configured
    # fraction is used; we never add this estimate to ExposureTracker's dose.
    rate = max(float(current_smoke), float(predicted_smoke)*config['predicted_dose_fraction'])
    return remaining/rate if rate >= config['minimum_dose_rate'] else math.inf


def personal_hazard_eta(environmental_eta, dose_eta):
    return min(environmental_eta, dose_eta)
