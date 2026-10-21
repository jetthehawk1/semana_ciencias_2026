from pathlib import Path
import sys,json,math
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from simulation.adaptive_exits import AdaptiveExitController
from simulation.hazard_impact import HazardEvacuationController
from tools.compare_evacuation_modes_v2 import run_case
original=AdaptiveExitController.indoor_candidates
def candidates(self,person,distance,current_distance,occupied,blocked):
    if self.safety_policy is not None:
        plain=HazardEvacuationController.indoor_candidates(self,person,distance,current_distance,occupied,blocked)
        safe=[p for p in plain if self.safety_policy.step_safe(person,p)]
        if not safe and math.isfinite(current_distance) and self.safety_policy.hazard.time_to_fire(*person.position)>self.safety_policy.fire_safety['imminent_margin_turns']:
            return []
    return original(self,person,distance,current_distance,occupied,blocked)
AdaptiveExitController.indoor_candidates=candidates
variant=sys.argv[1] if len(sys.argv)>1 else 'queue'
if variant=='front':
    original_step=AdaptiveExitController.step_with_hazards
    def step(self,tracker,burning,*,priority_by_person=None):
        return original_step(self,tracker,burning,priority_by_person={pid:0 for pid in self.ids})
    AdaptiveExitController.step_with_hazards=step
case=json.loads((ROOT/'reports/evacuation_comparison_v2/S02_intelligent.json').read_text())['scenario']
result=run_case(case,'intelligent')
(ROOT/f'reports/sexta_fase/indoor_{variant}_hypothesis.json').write_text(json.dumps(result,indent=2))
print(result['metrics'],flush=True)
