"""Fixed pedagogical summary. All original metrics remain independently visible."""
from __future__ import annotations


def safety_score(metrics, population, turns, config):
    denominators = dict(incapacitated=population, fire_contacts=population,
        accumulated_smoke_dose=population*config['reference_dose'],
        unsafe_waiting_person_turns=population*max(1, turns),
        destination_became_unsafe_before_arrival=population)
    penalty = sum(weight*min(1., metrics[key]/denominators[key])
                  for key, weight in config['weights'].items())
    return max(0., min(100., 100.-penalty))
