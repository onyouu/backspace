"""Isolated real-document relation probe, NOT a whole-model accuracy benchmark.

The actual workspace has no completed biology Teacher Model with 3–5 hypotheses.
Three explicit provisional probe statements are therefore seeded from original pages.
--live compares one bounded NVIDIA reinterpretation call against six Jev updates.
It does not pretend this is the unavailable legacy exam-to-model run.
"""
import argparse
import copy
import hashlib
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backspace_mvp.model import read_json
from backspace_mvp.pipeline import digest, save
from backspace_mvp.contracts import obj, TEXT
from backspace_mvp.llm_provider import create_provider
from backspace_mvp.jev import JevProvider
from backspace_mvp.semantic_control import SemanticControl
from backspace_mvp.teacher_update import TeacherModelUpdateEngine
from backspace_mvp.teacher_incremental import evidence_verifier


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--out', type=Path, default=Path('output/teacher_incremental_validation'))
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    memory = Path('state/web/workspace/teacher/memory/notes')
    notes = [read_json(p) for p in memory.glob('*.json')]
    rows = {n['provenance']['locator']: n for n in notes if n['provenance']['source_file'].startswith('(3)') and n.get('review_status') != 'rejected'}
    chosen = [rows[p] for p in ('p4', 'p5', 'p6', 'p2')]
    source_id = chosen[0]['provenance']['source_id']; sha = chosen[0]['provenance']['source_sha256']
    files = read_json('state/web/workspace/files.json')
    file = next(r for r in files if r['name'] == chosen[0]['provenance']['source_file'])
    pdf = Path('state/web/workspace/uploads') / (file['id']+file['suffix'])
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != sha:
        raise ValueError('Real original PDF hash changed')
    for n in chosen:
        text = (memory / (n['id']+'.md')).read_text(encoding='utf-8')
        if digest(text) != n['content_hash']: raise ValueError('Stored note body changed')
    scope = {'teacher_id': 'isolated-real-page-probe', 'subject': '생명과학'}
    source = {'id': source_id, 'sha256': sha, 'excerpts': [
        {'locator': n['provenance']['locator'], 'text': n['provenance']['quote']} for n in chosen]}
    data = {'sources': [source]}; evidence = []
    for n in chosen:
        p = n['provenance']; quote = p['quote']
        evidence.append({'id': 'ev_'+digest([source_id, p['locator'], quote])[:24],
            'kind': 'material_concept', 'origin_id': n['id'], 'citations': [{
                'source': source_id, 'source_sha256': sha, 'source_title': p['source_file'],
                'locator': p['locator'], 'raw_evidence': quote, 'char_start': 0, 'char_end': len(quote)}],
            'details': {'note_id': n['id'], 'observation_status': 'native/OCR reading not independent human verification'}})
    statements = [
        '제공된 소화계 자료에서는 식사 후 혈당이 증가하는 이유를 소화·흡수 과정과 연결해 설명하도록 질문한다.',
        '제공된 소화계 자료에서는 소화 장소의 환경과 소화효소·분해 산물을 함께 비교하도록 구성한다.',
        '제공된 소화계 자료에서는 영양소 흡수 경로와 세포호흡의 연결을 강조한다.']
    hypotheses = [{'id': 'hyp_'+digest(['probe', s])[:24], 'statement': s,
        'applicable_context': {'concept_ids': [], 'reasoning_codes': [],
            'conditions': ['기관계 PDF의 지정한 페이지 범위만', '연습용 잠정 문장이며 검증된 기존 Teacher Model이 아님']}}
        for s in statements]
    pairs = [{'hypothesis': h, 'evidence': e, 'expected_class': 'relevant' if i < 3 else 'unrelated'}
        for i, e in enumerate(evidence) for h in (hypotheses[i:i+1] if i < 3 else hypotheses)]
    report = {'scope': 'Real PDF page microbenchmark with 3 newly seeded provisional probes, NOT legacy full-model rebuild',
        'limitation': 'No completed real biology model with 3–5 existing hypotheses was available. No exam pattern/teacher generalization accuracy claim.',
        'original_pdf': str(pdf.resolve()), 'original_sha256': sha, 'provenance_preserved': True,
        'pages': ['p4', 'p5', 'p6', 'p2'], 'relation_pairs': len(pairs), 'live': args.live,
        'baseline': None, 'incremental': None}
    save(args.out / 'probe_inputs.json', {'scope': scope, 'evidence': evidence, 'hypotheses': hypotheses, 'pairs': pairs})
    if not args.live:
        save(args.out / 'benchmark.json', report); return
    llm = create_provider(task='hypothesis', usage_path=args.out / 'baseline_usage.json')
    contract = obj({'interpretations': {'type': 'array', 'items': obj({'hypothesis_id': TEXT,
        'statement': TEXT, 'evidence_ids': {'type': 'array', 'items': TEXT}}), 'maxItems': 3}})
    import json
    start = time.perf_counter(); baseline = None; failure = None
    try:
        baseline = llm.complete('Reinterpret the THREE supplied conditional hypotheses using only the exact original '
            'evidence. Return at most three concise Korean statements with only supplied evidence IDs. '
            'Do not infer private intent/personality, do not treat unrelated literature as a contradiction. '
            'This is a small comparison probe, not a full teacher model.\n'+json.dumps({'hypotheses': hypotheses,
                'evidence': evidence}, ensure_ascii=False), contract, stage='benchmark:teacher-reinterpretation', max_tokens=1200)
        save(args.out / 'baseline_output.json', baseline)
    except (ValueError, OSError, TimeoutError): failure = 'generation_pending'
    report['baseline'] = {'nvidia_calls': len(llm.attempts), 'jev_calls': 0,
        'latency_seconds': round(time.perf_counter()-start, 3), 'status': 'completed' if baseline else failure,
        'network_failures': sum(a['status'] in ('timeout', 'transport_error', 'http_error') for a in llm.attempts),
        'invalid_response_count': sum(a['status'] in ('invalid_json', 'invalid_response', 'schema_error') for a in llm.attempts),
        'output_limit_count': sum(a['status'] == 'output_limit' for a in llm.attempts),
        'hypotheses_reinterpreted': len(baseline['interpretations']) if baseline else 0,
        'incorrect_contradictions': None, 'incorrect_unrelated': None,
        'meaning': 'bounded slow reinterpretation comparator, not the old full pipeline'}
    jev = JevProvider(usage_path=args.out / 'incremental_usage.json')
    control = SemanticControl(args.out / 'decisions', provider=jev)
    engine = TeacherModelUpdateEngine(args.out / 'teacher_model', scope=scope, control=control,
        verify_evidence=evidence_verifier(data))
    for h in hypotheses: engine.seed_hypothesis(h, import_id='explicit_provisional_probe')
    version_before = engine.state['version']; start = time.perf_counter(); results = []
    for pair in pairs:
        result = engine.update_evidence(pair['evidence'], pair['hypothesis']['id'])
        results.append({'expected': pair['expected_class'], 'relation': result['relation'],
            'status': result['status'], 'relation_id': result['id']})
    delta = engine.state['version']-version_before
    report['incremental'] = {'nvidia_calls': 0, 'jev_calls': len(jev.attempts),
        'latency_seconds': round(time.perf_counter()-start, 3),
        'network_failures': sum(a['status'] != 'success' for a in jev.attempts),
        'hypothesis_updates': delta, 'hypotheses_changed': len({u['hypothesis_id'] for u in engine.state['updates'].values() if u['teacher_model_version_after'] > version_before}),
        'incorrect_contradictions': sum(r['expected'] == 'unrelated' and r['relation'] == 'contradicts' for r in results),
        'incorrect_unrelated': sum(r['expected'] == 'relevant' and r['relation'] == 'unrelated' for r in results),
        'pending_review': sum(r['status'] == 'pending_review' for r in results),
        'new_hypothesis_generation_count': 0, 'results': results,
        'classification_reference': 'developer-labelled relevance controls, not blinded human accuracy evaluation'}
    before = copy.deepcopy(engine.state); calls = len(jev.attempts)
    for pair in pairs: engine.update_evidence(pair['evidence'], pair['hypothesis']['id'])
    report['replay'] = {'jev_calls': len(jev.attempts)-calls, 'duplicate_updates': engine.state['version']-before['version']}
    save(args.out / 'benchmark.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
