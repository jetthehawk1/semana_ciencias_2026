"""Replay the unchanged 16 phase-six scenarios with phase-seven actors."""
from __future__ import annotations
import argparse
import json
import hashlib
import inspect
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT)]
from tools.compare_evacuation_modes_v2 import compare, report_json, input_fingerprint, run_case
from tools.compare_evacuation_modes import physical_digest


def finalize(report, output):
    """Preserve execution hashes; explicitly verify a later UI-only revision.

    Never authorizes changes to a simulation/routing module, data, executor or
    physical digest. No metric is edited and no old result is relabelled as a
    fresh execution. A manifest must have been captured before editing the UI.
    """
    current = input_fingerprint()
    revision = None
    if report['source_hash'] != current:
        manifest_path = ROOT/'reports/septima_fase/ui_revision_manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        assert manifest['benchmark_source_hash'] == report['source_hash']
        paths = sorted((ROOT/'src').rglob('*.py'))+sorted((ROOT/'data').rglob('*.json'))
        hashes = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        assert hashes.keys() == manifest['files'].keys(), 'Source/data inventory changed'
        changed = {name:dict(execution=old, final=hashes[name]) for name,old in manifest['files'].items()
                   if hashes[name] != old}
        assert changed and set(changed) <= set(manifest['allowed_ui_files']), 'Backend/data changed'
        assert all(name.startswith('src/dcc_app/') for name in changed)
        assert hashlib.sha256(inspect.getsource(run_case).encode()).hexdigest() == manifest['run_case_source_sha256']
        assert hashlib.sha256(inspect.getsource(physical_digest).encode()).hexdigest() == manifest['physical_digest_source_sha256']
        assert manifest['headless_backend_imports_no_dcc_app']
        revision = dict(changed_ui_files=changed, backend_and_all_data_unchanged=True,
                        manifest=str(manifest_path.relative_to(ROOT)),
                        note='Metrics executed with source_hash; final_source_hash includes later UI-only changes, separately tested/rendered.')
    path = ROOT/'reports/septima_fase/performance_after.json'
    performance = json.loads(path.read_text()) if path.exists() else None
    valid = performance and performance.get('source_hash') == current and performance['turns'] == 240
    report['final_source_hash'] = current
    report['validated_ui_only_revision'] = revision
    report['finalization_tool_hash'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['isolated_performance'] = performance if valid else None
    report['isolated_runtime_target_seconds_per_turn'] = 0.75
    report['readiness_checks']['isolated_runtime_target'] = performance['seconds_per_turn'] <= 0.75 if valid else None
    report['scenario_definition'] = 'Unchanged tools.compare_evacuation_modes_v2.benchmark_scenarios'
    (output/'summary.json').write_text(report_json(report), encoding='utf-8')
    return report


def run(turns=160, seed=2026, workers=3, output=None, resume=False):
    output = Path(output or ROOT/'reports/evacuation_comparison_v3')
    report = compare(turns, seed, workers, output, resume)
    return finalize(report, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--turns', type=int, default=160)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--finalize-only', action='store_true', help='Verify hashes and attach isolated timing; never executes or modifies metrics')
    args = parser.parse_args()
    if args.turns < 1 or not 1 <= args.workers <= 4:
        parser.error('Positive turns and 1..4 workers required')
    if args.finalize_only:
        output = Path(args.output_dir or ROOT/'reports/evacuation_comparison_v3')
        report = json.loads((output/'summary.json').read_text(encoding='utf-8'))
        assert report['complete'] and len(report['scenarios']) == 16
        finalize(report, output)
    else:
        run(args.turns, args.seed, args.workers, args.output_dir, args.resume)
