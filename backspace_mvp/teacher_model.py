"""Milestone v0.6: versioned Teacher Model assembled from observations and judgements."""
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from .jev import JevProvider
from .materials import validate_material_graph
from .model import read_json
from .patterns import load_active_graphs
from .scoring import checked_artifact


VERSION = 'teacher-model-1'
REVIEW_POLICY = {'version': 'review-priority-1', 'counter_threshold': .5,
                 'support_threshold': 2 / 3, 'quality_threshold': 2 / 3,
                 'confidence_threshold': .5}


def _digest(value):
    from .pipeline import digest
    return digest(value)


def _indexed(rows, key):
    result = {r[key]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError('Teacher Model 입력에 중복 ID가 있습니다.')
    return result


def _check_dimensions(dimensions):
    for key, value in dimensions.items():
        if value['status'] != 'scored':
            continue
        if value['dimension'] != key:
            raise ValueError('점수 차원 이름이 입력 항목과 다릅니다.')
        JevProvider.validate_response({'model': value['model'], 'answers': {key: value['raw_answer']}},
                                      {key: value['rubric']})
        normalized = value['raw_answer']['score'] / (len(value['rubric']['criteria']) - 1)
        if abs(normalized - value['normalized_score']) > 1e-9:
            raise ValueError('원 Jev 점수와 정규화 값이 다릅니다.')


def _review_priority(score):
    if score is None:
        return 'pending_scoring'
    dims = score['dimensions']
    required = [dims[k] for k in ('support', 'counter', 'evidence_quality')]
    if any(v['status'] != 'scored' for v in required):
        return 'insufficient_observation'
    if dims['counter']['normalized_score'] >= REVIEW_POLICY['counter_threshold']:
        return 'counter_evidence_review'
    if any(v['raw_answer']['confidence'] < REVIEW_POLICY['confidence_threshold'] for v in required):
        return 'uncertain_judgement_review'
    if (dims['support']['normalized_score'] < REVIEW_POLICY['support_threshold']
            or dims['evidence_quality']['normalized_score'] < REVIEW_POLICY['quality_threshold']):
        return 'weak_support_review'
    return 'provisional_support'


def consistency_context(model, hypothesis, max_ideals=8, max_concepts=12):
    """Bounded view of a previous model for v0.5; never send its full evidence archive."""
    context = hypothesis['applicable_context']
    concepts, codes = set(context['concept_ids']), set(context['reasoning_codes'])
    matching = [h for h in model['assessment_ideals'] if
        concepts.intersection(h['applicable_context']['concept_ids']) or
        codes.intersection(h['applicable_context']['reasoning_codes'])]
    related = [c for c in model['concept_importance'] if c['concept_id'] in concepts]
    return {'content_hash': model['content_hash'], 'scope': model['scope'],
        'assessment_ideals': [{k: h[k] for k in ('id', 'statement', 'applicable_context',
            'status', 'review_priority', 'counter_evidence_status', 'alternative_explanations')}
            for h in matching[:max_ideals]],
        'concept_importance': [{k: c[k] for k in ('concept_id', 'label', 'teacher_importance', 'status')}
                              for c in related[:max_concepts]],
        'coverage': {'related_ideals': len(matching), 'provided_ideals': min(len(matching), max_ideals),
            'related_concepts': len(related), 'provided_concepts': min(len(related), max_concepts)},
        'interpretation_status': 'previous_provisional_model_not_truth'}


def build_teacher_model(state, out=None, patterns_path=None, material_path=None,
                        hypotheses_path=None, scores_path=None, graphs_dir=None, incremental=None):
    from .pipeline import save, writable
    state = Path(state).resolve()
    paths = {name: Path(path).resolve() if path else state.parent / default for name, path, default in (
        ('patterns', patterns_path, 'patterns.json'), ('material', material_path, 'material_graph.json'),
        ('hypotheses', hypotheses_path, 'teacher_hypotheses.json'), ('scores', scores_path, 'teacher_scores.json'))}
    folder = Path(graphs_dir).resolve() if graphs_dir else state.parent / 'question_graphs'
    out = writable(out if out else state.parent / 'teacher_model.json')
    if out == state or out in paths.values() or folder == out.parent or folder in out.parents:
        raise ValueError('Teacher Model 출력은 입력 상태·문항 파일과 별도 경로를 사용하세요.')
    data = read_json(state)
    patterns = checked_artifact(paths['patterns'], 'patterns.schema.json', data['scope'])
    hypotheses = checked_artifact(paths['hypotheses'], 'teacher_hypotheses.schema.json', data['scope'])
    scores = checked_artifact(paths['scores'], 'teacher_scores.schema.json', data['scope'])
    material = validate_material_graph(read_json(paths['material']), data)
    expected = {'dataset_hash': _digest(data), 'patterns_hash': patterns['content_hash'],
                'material_graph_hash': material['content_hash']}
    if (patterns['dataset_hash'] != expected['dataset_hash'] or hypotheses['inputs'] != expected
            or any(scores['inputs'][k] != v for k, v in expected.items())
            or scores['inputs']['hypotheses_hash'] != hypotheses['content_hash']):
        raise ValueError('Teacher Model 입력 snapshot이 다릅니다. 패턴·가설·점수를 갱신하세요.')
    graphs, coverage = load_active_graphs(data, folder, patterns['coverage']['exam_filter'])
    snapshots = [{'question_id': g['question_id'], 'exam_id': g['exam_id'], 'revision': g['revision'],
                  'content_hash': g['content_hash']} for g in graphs]
    if patterns['coverage'] != coverage or patterns['input_graphs'] != snapshots:
        raise ValueError('활성 문항과 패턴 snapshot이 다릅니다.')
    registry = _indexed(hypotheses['evidence_registry'], 'id')
    hyp_by_id = _indexed(hypotheses['hypotheses'], 'id')
    score_by_hyp = _indexed(scores['hypothesis_scores'], 'hypothesis_id')
    score_by_concept = _indexed(scores['concept_scores'], 'concept_id')
    concept_by_id = _indexed(data['concepts'], 'id')
    if not set(score_by_hyp).issubset(hyp_by_id) or not set(score_by_concept).issubset(concept_by_id):
        raise ValueError('점수에 원래 가설·개념이 없는 항목이 있습니다.')
    if (set(scores['selection']['hypothesis_ids']) != set(score_by_hyp)
            or set(scores['selection']['concept_ids']) != set(score_by_concept)):
        raise ValueError('점수 선택 범위와 실제 점수 항목이 다릅니다.')
    for label, all_ids in (('hypothesis', set(hyp_by_id)), ('concept', set(concept_by_id))):
        chosen = scores['selection'][label + '_ids']
        omitted = scores['selection']['omitted_' + label + '_ids']
        if (len(chosen) != len(set(chosen)) or len(omitted) != len(set(omitted))
                or set(chosen) & set(omitted) or set(chosen) | set(omitted) != all_ids):
            raise ValueError('점수 대상의 선택·제외 범위가 전체 입력과 다릅니다.')
    material_nodes = {c['id']: c for c in material['concepts']}
    concept_importance = []
    for cid, concept in sorted(concept_by_id.items()):
        judgement = score_by_concept.get(cid)
        observations = []
        for graph in graphs:
            node = next((n for n in graph['nodes'] if n['kind'] == 'concept' and n['details']['concept_id'] == cid), None)
            if node:
                observations.append({'question_id': graph['question_id'], 'exam_id': graph['exam_id'],
                    'question_graph_hash': graph['content_hash'], 'evidence': node['evidence']})
        importance = judgement['teacher_salience'] if judgement else None
        if judgement:
            _check_dimensions(judgement['dimensions'])
            if (judgement['label'] != concept['label'] or judgement['statistics']['exam_support'] != len(observations)
                    or judgement['statistics']['exam_denominator'] != len(graphs)):
                raise ValueError('개념 점수의 라벨·시험 support/분모가 관찰과 다릅니다.')
            scored = {k: v for k, v in judgement['dimensions'].items() if v['status'] == 'scored'}
            weights = judgement['summary']['weights']
            weight = sum(weights[k] for k in scored)
            summary = (sum(weights[k] * v['normalized_score'] for k, v in scored.items()) / weight
                       if weight >= .65 and all(k in scored for k in ('recurrence', 'exam_relevance', 'evidence_quality')) else None)
            if (abs(weight - judgement['summary']['available_weight']) > 1e-9
                    or (summary is None) != (importance is None)
                    or (summary is not None and abs(summary - importance) > 1e-9)):
                raise ValueError('개념 중요도 요약과 원 차원·사용 가중치가 다릅니다.')
        concept_importance.append({'concept_id': cid, 'label': concept['label'], 'aliases': concept['aliases'],
            'teacher_importance': importance, 'status': 'provisional' if importance is not None else
                ('not_scored' if judgement is None else 'insufficient_observation'),
            'judgement': judgement, 'material_observations': material_nodes.get(cid),
            'question_observations': observations})
    concept_importance.sort(key=lambda c: (c['teacher_importance'] is None,
        -(c['teacher_importance'] if c['teacher_importance'] is not None else 0), c['concept_id']))
    ideals = []
    for hid, hypothesis in sorted(hyp_by_id.items()):
        refs = hypothesis['supporting_evidence'] + hypothesis['counter_evidence']
        if any(r['evidence_id'] not in registry for r in refs):
            raise ValueError('가설의 근거가 evidence registry에 없습니다.')
        judgement = score_by_hyp.get(hid)
        if judgement:
            _check_dimensions(judgement['dimensions'])
            evidence_ids = [r['evidence_id'] for r in judgement['evidence_scores']]
            available = {r['evidence_id'] for r in refs}
            if (len(evidence_ids) != len(set(evidence_ids)) or not set(evidence_ids).issubset(available)
                    or set(evidence_ids) != set(judgement['selected_evidence_ids'])
                    or set(judgement['omitted_evidence_ids']) != available - set(evidence_ids)):
                raise ValueError('가설 점수의 선택·제외 근거가 원 가설과 다릅니다.')
            for row in judgement['evidence_scores']:
                _check_dimensions(row['dimensions'])
        priority=_review_priority(judgement)
        validation=hypothesis.get('jev_validation',{})
        if validation.get('summary_status')=='contradicts':priority='counter_evidence_review'
        elif validation and (validation.get('needs_reanalysis') or validation.get('summary_status') in ('insufficient','irrelevant','needs_review')):
            priority='uncertain_judgement_review'
        ideals.append({**hypothesis, 'scoring_status': 'judged_provisional' if judgement else 'pending_jev',
            'judgement': judgement, 'review_priority': priority})
    dominant = {kind: [r for r in patterns['patterns'][kind]
        if r['mode'] == 'reasoning_structure' and r['is_repeated'] and r['meets_min_support']]
        for kind in ('nodes', 'edges', 'paths', 'subgraphs')}
    body = {'schema_version': '1.0', 'architecture_version': 'teacher-intelligence-0.1',
        'implementation_milestone': '0.6', 'model_version': VERSION, 'scope': data['scope'],
        'status': 'provisional_evidence_model', 'actual_student_behavior': 'not_observed',
        'inputs': {**expected, 'hypotheses_hash': hypotheses['content_hash'], 'scores_hash': scores['content_hash'],
                  'consistency_reference_model_hash': scores['inputs']['teacher_model_hash']},
        'coverage': {'pattern_coverage': coverage, 'hypothesis_selection': hypotheses['selection'],
                     'scoring_selection': scores['selection']},
        'counts': {'concepts': len(concept_importance), 'scored_concepts': len(score_by_concept),
            'questions': len(graphs), 'hypotheses': len(ideals), 'scored_hypotheses': len(score_by_hyp)},
        'concept_importance': concept_importance, 'dominant_reasoning': dominant,
        'reasoning_basis': 'repeated_required_graph_structure_not_verified_teacher_preference',
        'assessment_ideals': ideals, 'evidence_registry': list(registry.values()),
        'material_relations': material['relations'], 'material_sources': material['sources'],
        'input_question_graphs': snapshots, 'review_policy': REVIEW_POLICY,
        'score_meaning': 'rubric_position_and_weighted_summary_not_truth_probability'}
    if incremental is not None:
        body['incremental'] = incremental
    fingerprint = _digest(body)
    old = checked_artifact(out, 'teacher_model.schema.json', data['scope']) if out.exists() else None
    if old and old['content_hash'] == fingerprint:
        return old
    value = {**body, 'content_hash': fingerprint, 'revision': old['revision'] + 1 if old else 1,
             'previous_hash': old['content_hash'] if old else None, 'updated_at': datetime.now(timezone.utc).isoformat()}
    Draft202012Validator(read_json(Path(__file__).parent / 'schemas/teacher_model.schema.json')).validate(value)
    if old:
        save(out.parent / 'teacher_model_history' / f"{out.stem}-r{old['revision']}-{old['content_hash'][:16]}.json", old)
    save(out, value)
    return value
