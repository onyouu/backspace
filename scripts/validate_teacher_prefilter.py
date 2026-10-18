"""Bounded live Jev probe using verified inputs from validate_teacher_incremental.

Uses three explicitly provisional statements, not a completed real Teacher Model.
Never requests NVIDIA or runs the application pipeline. Outputs remain local.
"""
import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backspace_mvp.model import read_json
from backspace_mvp.pipeline import save
from backspace_mvp.jev import JevProvider
from backspace_mvp.semantic_control import SemanticControl
from backspace_mvp.teacher_incremental import evidence_verifier
from backspace_mvp.teacher_update import TeacherModelUpdateEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    inputs = read_json(args.input)
    previous = read_json(args.input.with_name('benchmark.json'))
    pdf = Path(previous['original_pdf'])
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != previous['original_sha256']:
        raise ValueError('Original PDF changed: regenerate verified probe inputs.')
    report = {'scope': 'Four real PDF pages, three newly seeded provisional statements, NOT an existing teacher model',
        'existing_real_hypotheses': 0, 'provisional_statements': len(inputs['hypotheses']),
        'relation_pairs_available': len(inputs['pairs']), 'nvidia_calls': 0,
        'original_sha256': previous['original_sha256'], 'live': args.live}
    if not args.live:
        save(args.out / 'benchmark.json', report)
        return
    provider = JevProvider(usage_path=args.out / 'usage.json')
    control = SemanticControl(args.out / 'decisions', provider=provider)
    sources = {}
    for e in inputs['evidence']:
        for c in e['citations']:
            source = sources.setdefault(c['source'], {'id': c['source'], 'sha256': c['source_sha256'], 'excerpts': []})
            source['excerpts'].append({'locator': c['locator'], 'text': c['raw_evidence']})
    engine = TeacherModelUpdateEngine(args.out / 'teacher_model', scope=inputs['scope'], control=control,
        verify_evidence=evidence_verifier({'sources': list(sources.values())}))
    for h in inputs['hypotheses']: engine.seed_hypothesis(h, import_id='explicit_provisional_probe')
    groups = {}
    for pair in inputs['pairs']:
        group = groups.setdefault(pair['evidence']['id'], {'evidence': pair['evidence'], 'hypotheses': [],
            'expected': pair['expected_class']})
        group['hypotheses'].append(pair['hypothesis']['id'])
    started = time.perf_counter()
    before = engine.state['version']
    gates = [engine.update_related_evidence(g['evidence'], g['hypotheses']) for g in groups.values()]
    relations = list(engine.state['relations'].values())
    expected = {g['evidence']['id']: g['expected'] for g in groups.values()}
    report.update(jev_calls=len(provider.attempts), latency_seconds=round(time.perf_counter()-started, 3),
        network_failures=sum(a['status'] != 'success' for a in provider.attempts),
        hypothesis_updates=engine.state['version']-before,
        hypotheses_changed=len({u['hypothesis_id'] for u in engine.state['updates'].values()
            if u['teacher_model_version_after'] > before}),
        generic_preserved=sum(g['status'] == 'generic_evidence_preserved' for g in gates),
        gate_pending=sum(g['status'] == 'pending_review' for g in gates),
        relation_pending=sum(r['status'] == 'pending_review' for r in relations),
        relation_calls=sum(a['stage'] == 'teacher_relation' for a in provider.attempts),
        incorrect_contradictions=sum(expected[r['evidence_id']] == 'unrelated' and r['relation'] == 'contradicts' for r in relations),
        incorrect_unrelated=sum(expected[r['evidence_id']] == 'relevant' and r['relation'] == 'unrelated' for r in relations),
        potentially_missed_relevant=sum(expected[g['evidence_id']] == 'relevant' and g['status'] == 'generic_evidence_preserved' for g in gates),
        provenance_preserved=all(g['provenance'] == groups[g['evidence_id']]['evidence']['citations'] for g in gates),
        classification_reference='developer-labelled relevance controls, NOT blinded accuracy evaluation')
    checkpoint = copy.deepcopy(engine.state)
    calls = len(provider.attempts)
    for g in groups.values(): engine.update_related_evidence(g['evidence'], g['hypotheses'])
    report['replay'] = {'jev_calls': len(provider.attempts)-calls, 'duplicate_updates': engine.state['version']-checkpoint['version']}
    save(args.out / 'benchmark.json', report)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__': main()
