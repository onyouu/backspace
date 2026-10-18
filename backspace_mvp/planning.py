"""Compile explicit question demands into auditable tasks; no student inference."""
from .pipeline import digest


def task_from_step(q, step, report, exam_format):
    edges = [e for e in q['edges'] if step['id'] in (e['from'], e['to'])]
    concept_ids = sorted({node for e in edges for node in (e['from'], e['to']) if node in q['concept_ids']})
    claims = [c for c in q.get('claims', []) if c['id'] in step.get('claim_ids', [])]
    evidence = list(step.get('evidence', q['evidence']))
    evidence.extend(ref for c in claims for ref in c['evidence'])
    material_ids = {s['id'] for s in report['sources'] if s['kind'] == 'learning_material'}
    material_refs = [ref for ref in evidence if ref['source_id'] in material_ids]
    uncertain = any(c['review_status'] != 'supported' for c in claims)
    review_status = 'needs_reference_review' if uncertain else 'ai_reviewed'
    if q.get('analysis_version') not in ('grounded-2.2', 'grounded-2.3'):
        review_status = 'legacy_needs_reanalysis'
    return {'id': 'demand:' + q['id'] + ':' + step['id'], 'concept_id': concept_ids[0] if len(concept_ids) == 1 else '',
        'activity': step['practice'] + '\n제출물: ' + step['output'], 'question_ids': [q['id']], 'step_id': step['id'],
        'objective': step['label'], 'expected_output': step['output'],
        'success_criteria': step['success_criteria'], 'conditions': step['conditions'],
        'material_source_ids': sorted({ref['source_id'] for ref in material_refs}),
        'evidence': list({digest(r): r for r in evidence}.values()), 'claim_ids': step['claim_ids'],
        'review_status': review_status,
        'status': 'pending'}


def make_tasks(report, exam_format, previous):
    tasks = []
    for q in report['questions']:
        if q.get('analysis_version', '').startswith('grounded-'):
            tasks.extend(task_from_step(q, s, report, exam_format) for s in q['steps'])
        else:
            tasks.append({'id': 'legacy:' + q['id'], 'concept_id': '',
                'activity': f"문항 {q['title']}의 {exam_format} 답안을 작성하고 아래 필수 요소를 대조하세요.",
                'objective': q['intent']['objective'], 'expected_output': f"문항 {q['title']}의 답안과 근거 설명",
                'success_criteria': q['intent']['success_criteria'], 'conditions': [],
                'question_ids': [q['id']], 'step_id': '', 'material_source_ids': [],
                'evidence': q['evidence'], 'claim_ids': [],
                'review_status': 'legacy_needs_reanalysis', 'status': 'pending'})
    previous_by_id = {t['id']: t for t in previous}
    for task in tasks:
        # Completion is preserved only if the actual assignment and evidence still match.
        q = next(q for q in report['questions'] if q['id'] in task['question_ids'])
        relevant_claims = [c for c in q.get('claims', []) if c['id'] in task['claim_ids']]
        task['content_hash'] = digest({'task': {k: v for k, v in task.items() if k != 'status'},
                                      'claims': relevant_claims, 'exam_format': exam_format})
        old = previous_by_id.get(task['id'])
        if old and old.get('content_hash') == task['content_hash']:
            task['status'] = old['status']
    return tasks
