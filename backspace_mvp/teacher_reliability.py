"""Small scheduling and read-back checks for the existing notes-first builder."""
from collections import Counter
from pathlib import Path
from .pipeline import digest
from .model import read_json

VERSION = 'one-run-1'
CLOSED = {'processed', 'generic_evidence_preserved', 'represented_by_existing', 'no_new_pattern', 'pending_review'}


def note_bundles(notes, routes, scope):
    # A routed teacher signal must not be starved by alphabetically earlier topics.
    groups = {}
    signals = [e for e in notes if routes.get(e['id'], {}).get('teacher_signal') is True]
    if signals:
        groups['관찰된 설명·평가 요구'] = signals
    for e in notes:
        topic = ' / '.join(e['details'].get('topic', [])[:2]) or scope.get('subject', '자료')
        groups.setdefault(topic, []).append(e)
    bundles = []
    for topic, rows in groups.items():
        ranked = sorted(rows, key=lambda e: (routes.get(e['id'], {}).get('teacher_signal') is not True, e['id']))
        selected = []; seen = set()
        for e in ranked:
            sha = e['citations'][0]['source_sha256']
            if sha not in seen:
                selected.append(e); seen.add(sha)
            if len(selected) == 3: break
        if len(selected) < 2: continue
        identity = digest(['notes_candidate_v2', topic, selected])
        bundles.append((identity, topic, rows, selected))
    return bundles


def result_summary(registry, hypotheses, clusters, selection):
    counts = Counter(c.get('status') for c in clusters.values())
    pending = sum(counts[k] for k in ('pending_review', 'failed_retryable', 'integration_pending', 'budget_deferred'))
    retry_pending = sum(counts[k] for k in ('failed_retryable', 'integration_pending', 'budget_deferred'))
    cited = [h for h in hypotheses if h['supporting_evidence'] and h['applicable_context']['conditions']]
    if cited:
        kind = 'hypotheses_available'; message = '근거가 연결된 교사 가설을 저장했습니다. 적용 범위와 검토 상태를 확인하세요.'
    elif not registry:
        kind = 'insufficient_evidence'; message = '현재 원문과 일치하는 근거가 없습니다. 자료와 원문 검토 상태를 확인하세요.'
    elif retry_pending:
        kind = 'generation_pending'; message = '자료 근거는 저장됐지만 교사 가설 판정이 보류돼 있습니다. 아래 사유를 확인하세요.'
    else:
        kind = 'insufficient_evidence'; message = ('현재 자료의 교사 단서가 불확실해 가설을 확정하지 않았습니다. 원문과 시험문항을 검토하세요.'
            if counts['pending_review'] else '확인한 자료에서 교사 고유의 설명·평가 경향을 뒷받침할 근거가 부족합니다.')
    return {'kind': kind, 'message': message, 'scope': '현재 등록된 자료 범위',
            'cited_hypotheses': len(cited), 'pending_clusters': pending,
            'cluster_counts': dict(counts), 'selection': selection,
            'next_action': '설명·비교·근거 제시 요구가 드러난 시험 문항 또는 원문을 추가·검토하세요.' if not cited else '가설별 원문과 반례를 확인하세요.'}


def verify_model(path):
    """Read actual durable artifact; a completed job is not evidence of persistence."""
    from .scoring import checked_artifact
    path = Path(path)
    model = read_json(path)
    checked_artifact(path, 'teacher_model.schema.json', model['scope'])
    records = {e['id']: e for e in model['evidence_registry']}
    from .teacher_incremental import evidence_verifier
    # Historical teacher-model views embed material sources only. Question
    # evidence still points to exam sources in the saved dataset snapshot.
    sources = {s['id']: s for s in model['material_sources']}
    dataset = path.parent / 'dataset.json'
    if dataset.exists():
        for source in read_json(dataset).get('sources', []):
            sources[source['id']] = source
    verify = evidence_verifier({'sources': list(sources.values())})
    for e in records.values(): verify(e)
    cited = any(h['supporting_evidence'] and h['applicable_context']['conditions'] and
        all(e['evidence_id'] in records for e in h['supporting_evidence']) for h in model['assessment_ideals'])
    explicit_shortfall = model.get('result', {}).get('kind') == 'insufficient_evidence'
    understood = model['coverage'].get('understanding', {}).get('completed')
    usable = bool(cited or explicit_shortfall)
    if model.get('build_strategy'):
        usable = any(h.get('readiness') == 'usable' for h in model['assessment_ideals'])
    return model, {'MATERIAL_INGEST_SUCCESS': bool(understood if understood is not None else sources),
        'TEACHER_MODEL_PERSISTED': True, 'TEACHER_MODEL_USABLE': usable,
        'interpretation': '근거 부족 설명도 확인 가능한 결과이며, 검증된 가설이 있다는 뜻은 아닙니다.'}
