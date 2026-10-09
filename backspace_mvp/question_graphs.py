"""Milestone v0.2: isolated typed question graphs derived from reviewed source snapshots."""
import re
from pathlib import Path
from datetime import datetime, timezone
from jsonschema import Draft202012Validator


def filename(question_id):
    from .pipeline import digest
    return 'q_' + digest(question_id)[:20] + '.json'


def projection(data, question):
    from .pipeline import digest
    sources = {s['id']: s for s in data['sources']}
    concepts = {c['id']: c for c in data['concepts']}
    q = question
    qid = q['id']

    def citations(refs, confidence):
        from .perception import transcription_refs
        result = []
        for ref in refs:
            source = sources[ref['source_id']]
            text = next(p['text'] for p in source['excerpts'] if p['locator'] == ref['locator'])
            start = ref.get('start_offset',text.index(ref['quote']))
            page = re.fullmatch(r'(?:p|slide)(\d+)', ref['locator'])
            result.append({'source': source['id'], 'source_title': source['title'], 'source_kind': source['kind'],
                'source_sha256': source['sha256'], 'page': int(page[1]) if page else None,
                'locator': ref['locator'], 'question_id': qid, 'raw_evidence': ref['quote'],
                'char_start': start, 'char_end': start + len(ref['quote']), 'offset_policy': 'source_span' if ref.get('span_id') else 'first_exact_match',
                'confidence': confidence,
                'transcription':transcription_refs(source,ref['locator'],start,start+len(ref['quote']))})
        return list({digest(r): r for r in result}.values())

    nodes, edges = [], []

    def node(id, kind, label, confidence, refs, details, status='required'):
        nodes.append({'id': id, 'kind': kind, 'label': label, 'confidence': confidence,
                      'evidence': citations(refs, confidence), 'observation_status': status, 'details': details})

    def edge(a, b, relation, explanation, confidence, refs):
        edges.append({'id': 'qe_' + digest([qid, a, b, relation])[:20], 'from': a, 'to': b,
                      'relation': relation, 'explanation': explanation, 'confidence': confidence,
                      'evidence': citations(refs, confidence)})

    node('task:t0', 'task', q['task']['description'], q['task']['confidence'], q['task']['evidence'],
         {'description': q['task']['description']})
    for cid in q['concept_ids']:
        values = [c['value'] for c in q['concept_confidences'] if c['concept_id'] == cid]
        node('concept:' + cid, 'concept', concepts[cid]['label'], min(values), q['evidence'],
             {'concept_id': cid, 'aliases': concepts[cid]['aliases'], 'confidence_aggregation': 'min_self_reports',
              'extraction_confidences': [c for c in q['concept_confidences'] if c['concept_id'] == cid]})
    for step in q['steps']:
        rid, uid = 'reasoning:' + step['id'], 'understanding:' + step['id']
        node(rid, 'reasoning', step['label'], step['confidence'], step['evidence'],
             {k: step[k] for k in ('code', 'input', 'output', 'conditions', 'practice', 'claim_ids')})
        refs = step['assessment_evidence'] or step['evidence']
        claim_rows = [c for c in q['claims'] if c['id'] in step['claim_ids']]
        node(uid, 'evidence_of_understanding', step['output'], step['confidence'], refs,
             {'expected_artifact': step['output'], 'success_criteria': step['success_criteria'],
              'claim_ids': step['claim_ids'], 'criteria_status': 'candidate',
              'basis': 'answer_key_cited' if any(sources[e['source_id']]['kind'] == 'answer_key' for e in refs)
                       else 'inferred_from_question_or_material',
              'claim_review_status': 'needs_reference_review' if any(c['review_status'] != 'supported' for c in claim_rows)
                                     else 'ai_reviewed'}, status='required_candidate')
        edge('task:t0', rid, 'requires_reasoning', '이 문항의 Task에서 요구하는 사고 수행.', step['confidence'], step['evidence'])
        edge(rid, uid, 'demonstrated_by', '이 사고 수행의 답안·산출물 및 이해 증거 후보.', step['confidence'], refs)
        edge(uid, 'intent:h0', 'supports_intent_candidate', '출제 의도 후보의 근거이며 실제 이해 관찰이 아님.',
             q['intent']['confidence'], refs)
    for row in q['concept_confidences']:
        edge('concept:' + row['concept_id'], 'reasoning:' + row['step_id'], 'applied_in',
             '공통 Concept을 이 문제의 요구 사고에 적용한다.', row['value'], q['evidence'])
    for row in q['edges']:
        if row['from'].startswith('s') and row['to'].startswith('s') and row['from'] not in q['concept_ids'] and row['to'] not in q['concept_ids']:
            step = next(s for s in q['steps'] if s['id'] == row['from'])
            edge('reasoning:' + row['from'], 'reasoning:' + row['to'], row['relation'], row.get('explanation', row['relation']),
                 step['confidence'], row['evidence'])
    node('intent:h0', 'assessment_intent', q['intent']['objective'], q['intent']['confidence'], q['intent']['evidence'],
         {'status': 'hypothesis', 'review_status': q['intent']['review_status'],
          'success_criteria': q['intent']['success_criteria']}, status='hypothesis')
    claims = [{**{k: c[k] for k in ('id', 'statement', 'conditions', 'review_status', 'review_reason', 'origin', 'step_id', 'confidence')},
               'evidence': citations(c['evidence'], c['confidence'])} for c in q['claims']]
    used = {ref['source'] for n in nodes for ref in n['evidence']} | {ref['source'] for c in claims for ref in c['evidence']}
    used.update(b['source_id'] for b in q['answer_key_context']['blocks'])
    used.update(b['source_id'] for b in q['retrieval']['selected_blocks'])
    return {'schema_version': '1.0', 'architecture_version': 'teacher-intelligence-0.1', 'implementation_milestone': '0.2',
            'question_id': qid, 'exam_id': q['exam_id'], 'question_number': q['title'], 'scope': data['scope'],
            'analysis_version': q['analysis_version'], 'analysis_status': q['analysis_status'],
            'confidence': q['confidence'],
            'actual_student_behavior': 'not_observed', 'confidence_meaning': 'extraction_self_report_not_teacher_importance',
            'input_context_hash': digest([q['retrieval'], q['answer_key_context']]),
            'answer_key_context': q['answer_key_context'], 'answer_requirements': q['answer_requirements'],
            'sources': [{k: sources[sid][k] for k in ('id', 'title', 'path', 'sha256', 'kind', 'format')} for sid in sorted(used)],
            'nodes': nodes, 'edges': edges, 'claims': claims, 'review_history': q['review_history']}


def validate_question_graph(graph, data):
    from .model import validate, read_json
    from .pipeline import digest
    validate(data)
    schema = read_json(Path(__file__).parent / 'schemas/question_graph.schema.json')
    Draft202012Validator(schema).validate(graph)
    question = next((q for q in data['questions'] if q['id'] == graph['question_id']), None)
    if not question or question.get('analysis_version') != 'grounded-2.3':
        raise ValueError('Question Graph는 v0.2 계약으로 재분석한 문항에서 생성하세요.')
    expected = projection(data, question)
    if {k: graph[k] for k in expected} != expected or graph['content_hash'] != digest(expected):
        raise ValueError('Question Graph 구조·근거·해시가 해당 문항과 다릅니다.')
    ids = {n['id'] for n in graph['nodes']}
    if len(ids) != len(graph['nodes']) or any(e['from'] not in ids or e['to'] not in ids for e in graph['edges']):
        raise ValueError('Question Graph 노드 또는 연결 참조가 잘못되었습니다.')
    return graph


def export_question_graphs(data, folder):
    from .model import validate, read_json
    from .pipeline import digest, save, writable
    validate(data)
    folder = writable(folder)
    old_index = read_json(folder / 'index.json') if (folder / 'index.json').exists() else None
    if old_index and old_index['scope'] != data['scope']:
        raise ValueError('다른 교사 범위의 Question Graph를 덮어쓸 수 없습니다.')
    entries, legacy = [], []
    for q in data['questions']:
        if q.get('analysis_version') != 'grounded-2.3':
            legacy.append(q['id'])
            continue
        projected = projection(data, q)
        fingerprint = digest(projected)
        path = folder / filename(q['id'])
        old = read_json(path) if path.exists() else None
        if old and old['content_hash'] == fingerprint:
            graph = validate_question_graph(old, data)
        else:
            if old and (old['question_id'] != q['id'] or old['scope'] != data['scope']):
                raise ValueError('기존 Question Graph의 문항 ID·범위가 다릅니다.')
            graph = {**projected, 'content_hash': fingerprint, 'revision': old['revision'] + 1 if old else 1,
                     'previous_hash': old['content_hash'] if old else None, 'updated_at': datetime.now(timezone.utc).isoformat()}
            validate_question_graph(graph, data)
            if old:
                save(folder / 'history' / f"{path.stem}-r{old['revision']}-{old['content_hash'][:16]}.json", old)
            save(path, graph)
        entries.append({'question_id': q['id'], 'exam_id': q['exam_id'], 'question_number': q['title'],
                        'file': path.name, 'revision': graph['revision'], 'content_hash': fingerprint})
    active = {e['question_id'] for e in entries}
    for old_entry in old_index['questions'] if old_index else []:
        if old_entry['question_id'] in active:
            continue
        # Archive only a file we own; an edited index cannot select arbitrary paths.
        path = folder / filename(old_entry['question_id'])
        if path.exists():
            old = read_json(path)
            if old['question_id'] != old_entry['question_id']:
                raise ValueError('폐기할 Question Graph의 소유 문항이 다릅니다.')
            save(folder / 'history' / f"retired-{path.stem}-{digest(old)[:16]}.json", old)
            path.unlink()
    index = {'schema_version': '1.0', 'scope': data['scope'], 'questions': entries, 'needs_reanalysis': legacy}
    if index != old_index:
        save(folder / 'index.json', index)
    return index
