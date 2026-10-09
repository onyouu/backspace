"""Contract fixtures verify the pipeline, not teacher/scientific accuracy."""
import copy
import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from backspace_mvp.model import read_json
from backspace_mvp.pipeline import save
from backspace_mvp.materials import export_material_graph
from backspace_mvp.question_graphs import export_question_graphs
from backspace_mvp.patterns import build_patterns, mine_patterns, load_active_graphs
from backspace_mvp.hypotheses import build_teacher_hypotheses
from backspace_mvp.scoring import build_teacher_scores
from backspace_mvp.teacher_model import build_teacher_model
from backspace_mvp.study_plan import generate_study_plan, update_study_plan
from backspace_mvp.jev import JevProvider

ROOT = Path(__file__).resolve().parents[1]


class LLMFixture:
    model = last_model = 'contract-fixture'
    calls = 0
    invalid = False

    def complete(self, prompt, schema, **kwargs):
        self.calls += 1
        packet = json.loads(prompt[prompt.index('{'):])
        if 'blueprints' in packet:
            return {'tasks': [{'task_id': 'bad' if self.invalid else b['task_id'],
                'activity': '제공 자료의 조건을 비교한다.', 'objective': '근거와 조건 확인',
                'expected_output': '원문을 인용한 비교표', 'success_criteria': ['원문 위치 명시'],
                'conditions': []} for b in packet['blueprints']]}
        pattern = packet['patterns'][0]
        cards = [c for c in packet['evidence_cards'] if c['kind'] == 'question'
                 and c['origin_id'] in pattern['question_ids']][:2]
        return {'hypotheses': [{'statement': '제공된 두 문항에서는 조건 비교의 수행이 반복적으로 요구된다.',
            'pattern_ids': [pattern['pattern_id']],
            'supporting_evidence': [{'evidence_id': c['evidence_id'], 'reason': '반복 구조의 제공 문항 근거'} for c in cards],
            'counter_evidence': [], 'counter_evidence_status': 'no_counter_identified_in_provided_context',
            'applicable_context': {'exam_ids': sorted({c['details']['exam_id'] for c in cards}),
                'concept_ids': sorted({n['details']['concept_id'] for c in cards for n in c['details']['nodes'] if n['kind'] == 'concept'}),
                'reasoning_codes': ['compare'], 'conditions': ['제공한 두 문항 범위']},
            'alternative_explanations': ['단원 특성일 수 있다.', '시험 형식의 영향일 수 있다.'],
            'next_validation_data': ['다른 단원의 시험 문항'], 'limitations': ['합성 샘플로 실제 교사 판단을 검증하지 않음']}],
            'abstention_reason': ''}


class JevFixture:
    model = 'jev-fixture'
    endpoint = JevProvider.endpoint
    calls = 0
    fail = False

    def score(self, state, questions, **kwargs):
        self.calls += 1
        if self.fail:
            raise ValueError('fixture transport failure')
        answers = {}
        for qid, question in questions.items():
            level = 0 if 'counter' in qid else 2
            answers[qid] = {'type': 'score', 'score': level, 'confidence': .8,
                'legend': {str(i): text for i, text in enumerate(question['criteria'])},
                'probabilities': {str(i): float(i == level) for i in range(len(question['criteria']))}}
        return {'model': self.model, 'answers': answers, 'usage': None}


def seed(folder, fixture='data/question_graph_v02/offline_fixture.json'):
    root = Path(folder)
    state = root / 'dataset.json'
    data = read_json(ROOT / fixture)
    save(state, data)
    export_material_graph(data, root / 'material_graph.json')
    export_question_graphs(data, root / 'question_graphs')
    return state


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = seed(self.root)
        self.llm, self.jev = LLMFixture(), JevFixture()

    def build(self):
        patterns = build_patterns(self.state)
        hypotheses = build_teacher_hypotheses(self.state, provider=self.llm, max_hypotheses=1,
            max_patterns=1, max_questions=2, max_material_items=1)
        scores = build_teacher_scores(self.state, provider=self.jev, max_concepts=2,
            max_hypotheses=1, max_evidence=2)
        model = build_teacher_model(self.state)
        return patterns, hypotheses, scores, model

    def plan(self, **kwargs):
        return generate_study_plan(self.root / 'teacher_model.json', self.state,
            max_concepts=2, days=1, daily_minutes=20, **kwargs)

    def test_full_chain_and_no_cost_replay(self):
        p, h, s, m = self.build()
        self.assertEqual(p['coverage']['included_questions'], 2)
        self.assertEqual(len(h['hypotheses']), 1)
        self.assertTrue(all(r['support'] <= 2 and r['denominator'] == 2
            for rows in p['patterns'].values() for r in rows))
        self.assertIsNone(s['hypothesis_scores'][0]['dimensions']['consistency']['normalized_score'])
        self.assertEqual(m['actual_student_behavior'], 'not_observed')
        calls = self.llm.calls, self.jev.calls
        before = {name: (self.root / name).read_bytes() for name in
                  ['patterns.json', 'teacher_hypotheses.json', 'teacher_scores.json', 'teacher_model.json']}
        self.build()
        self.assertEqual(calls, (self.llm.calls, self.jev.calls))
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in before})
        plan = self.plan(offline=True)
        self.assertEqual(plan['budget']['scheduled_minutes'], 20)
        self.assertGreater(plan['budget']['overflow_minutes'], 0)
        self.assertIsNone(plan['student_factors']['weakness'])
        self.assertEqual(plan, self.plan(offline=True))

    def test_progress_note_regeneration_and_history(self):
        self.build()
        plan = self.plan(offline=True)
        tid = plan['tasks'][0]['id']
        updated = update_study_plan(self.root / 'current_plan.json', 'progress', task_id=tid, status='completed')
        self.assertFalse(any(s['task_id'] == tid for s in updated['schedule']))
        self.assertEqual(updated, update_study_plan(self.root / 'current_plan.json', 'progress', task_id=tid, status='completed'))
        noted = update_study_plan(self.root / 'current_plan.json', 'constraint', text='답안에는 원문 근거를 남긴다.')
        self.assertTrue(noted['needs_revision'])
        final = self.plan(offline=True)
        self.assertFalse(final['needs_revision'])
        self.assertEqual(next(t['status'] for t in final['tasks'] if t['id'] == tid), 'completed')
        self.assertIn(noted['events'][-1]['id'], final['processed_event_ids'])
        self.assertTrue(list((self.root / 'plan_history').glob('*.json')))

    def test_online_contracts_and_invalid_regeneration_preserves_plan(self):
        self.build()
        plan = self.plan(jev=self.jev, llm=self.llm)
        self.assertEqual(plan['generation']['mode'], 'nvidia_generated')
        calls = self.llm.calls, self.jev.calls
        self.assertEqual(plan, self.plan(jev=self.jev, llm=self.llm))
        self.assertEqual(calls, (self.llm.calls, self.jev.calls))
        before = (self.root / 'current_plan.json').read_bytes()
        self.llm.invalid = True
        with self.assertRaises(ValueError):
            self.plan(jev=self.jev, llm=self.llm, refresh=True)
        self.assertEqual(before, (self.root / 'current_plan.json').read_bytes())

    def test_stale_input_and_pattern_budget_preserve_output(self):
        self.build()
        before = (self.root / 'patterns.json').read_bytes()
        with self.assertRaises(ValueError):
            build_patterns(self.state, max_candidates=1)
        self.assertEqual(before, (self.root / 'patterns.json').read_bytes())
        data = read_json(self.state)
        data['concepts'][0]['label'] += ' changed'
        save(self.state, data)
        with self.assertRaises(ValueError):
            build_teacher_hypotheses(self.state, provider=self.llm)

    def test_scoring_transport_failure_preserves_state(self):
        self.build()
        before = (self.root / 'teacher_scores.json').read_bytes()
        self.jev.fail = True
        with self.assertRaises(ValueError):
            build_teacher_scores(self.state, provider=self.jev, refresh=True, max_concepts=2)
        self.assertEqual(before, (self.root / 'teacher_scores.json').read_bytes())

    def test_patterns_count_questions_not_occurrences_and_keep_exam_denominators(self):
        data = read_json(self.state)
        graphs, coverage = load_active_graphs(data, self.root / 'question_graphs')
        graph = copy.deepcopy(graphs[0])
        compare = next(n for n in graph['nodes'] if n['kind'] == 'reasoning' and n['details']['code'] == 'compare')
        duplicate = copy.deepcopy(compare)
        duplicate['id'] = 'reasoning:duplicate_compare'
        graph['nodes'].append(duplicate)
        result = mine_patterns([graph], coverage, data['scope'])
        row = next(r for r in result['patterns']['nodes'] if r['mode'] == 'reasoning_structure'
                   and r['descriptor']['node']['code'] == 'compare')
        self.assertEqual((row['support'], row['occurrence_count'], row['is_repeated']), (1, 2, False))
        graphs[1]['exam_id'] = 'second_exam'
        result = mine_patterns(graphs, coverage, data['scope'])
        for rows in result['patterns'].values():
            for row in rows:
                self.assertEqual({r['denominator'] for r in row['by_exam']}, {1})
                self.assertEqual(row['support'], sum(r['support'] for r in row['by_exam']))

    def test_motif_isomorphism_and_direction_are_preserved(self):
        data = read_json(self.state)
        graphs, coverage = load_active_graphs(data, self.root / 'question_graphs')
        original = mine_patterns([graphs[0]], coverage, data['scope'])
        renamed = copy.deepcopy(graphs[0])
        mapping = {n['id']: 'renamed_' + str(i) for i, n in enumerate(reversed(renamed['nodes']))}
        for n in renamed['nodes']:
            n['id'] = mapping[n['id']]
        for e in renamed['edges']:
            e['from'], e['to'] = mapping[e['from']], mapping[e['to']]
        renamed['nodes'].reverse()
        renamed['edges'].reverse()
        altered = mine_patterns([renamed], coverage, data['scope'])
        for kind in ('nodes', 'edges', 'paths', 'subgraphs'):
            self.assertEqual({r['pattern_id'] for r in original['patterns'][kind]},
                             {r['pattern_id'] for r in altered['patterns'][kind]})
        for e in renamed['edges']:
            e['from'], e['to'] = e['to'], e['from']
        reversed_result = mine_patterns([renamed], coverage, data['scope'])
        self.assertNotEqual({r['pattern_id'] for r in original['patterns']['edges']},
                            {r['pattern_id'] for r in reversed_result['patterns']['edges']})

    def test_no_repeat_abstains_without_model_call(self):
        build_patterns(self.state, min_support=3)
        result = build_teacher_hypotheses(self.state, provider=self.llm)
        self.assertEqual(result['hypotheses'], [])
        self.assertEqual(self.llm.calls, 0)
        self.assertTrue(result['abstention_reason'])

    def test_previous_model_consistency_and_version_update(self):
        self.build()
        old = read_json(self.root / 'teacher_model.json')
        scores = build_teacher_scores(self.state, provider=self.jev, max_concepts=2, max_hypotheses=1,
            max_evidence=2, teacher_model_path=self.root / 'teacher_model.json')
        self.assertEqual(scores['hypothesis_scores'][0]['dimensions']['consistency']['status'], 'scored')
        new = build_teacher_model(self.state)
        self.assertEqual(new['revision'], old['revision'] + 1)
        self.assertEqual(new['previous_hash'], old['content_hash'])
        self.assertTrue(list((self.root / 'teacher_model_history').glob('*.json')))

    def test_changed_activity_resets_completed_task(self):
        self.build()
        plan = self.plan(jev=self.jev, llm=self.llm)
        tid = plan['tasks'][0]['id']
        update_study_plan(self.root / 'current_plan.json', 'progress', task_id=tid, status='completed')
        original_complete = self.llm.complete
        def changed(*args, **kwargs):
            value = original_complete(*args, **kwargs)
            value['tasks'][0]['activity'] = '다른 산출물을 요구하는 새 활동'
            return value
        self.llm.complete = changed
        new = self.plan(jev=self.jev, llm=self.llm, refresh=True)
        self.assertEqual(next(t['status'] for t in new['tasks'] if t['id'] == tid), 'pending')

    def test_cli_ingestion_through_plan_and_progress(self):
        from backspace_mvp.cli import main
        state = self.root / 'cli/dataset.json'
        fixture = str(ROOT / 'data/question_graph_v02/offline_fixture.json')
        with contextlib.redirect_stdout(io.StringIO()), \
                patch('backspace_mvp.llm_provider.create_provider', return_value=self.llm), \
                patch('backspace_mvp.scoring.JevProvider', wraps=JevProvider) as jev_class, \
                patch('urllib.request.urlopen', side_effect=AssertionError('Offline tests must never use the network')):
            # Keep the real response validator while replacing network construction.
            jev_class.return_value = self.jev
            main(['ingest_materials', '--input', fixture, '--state', str(state)])
            main(['analyze_exam', '--input', fixture, '--state', str(state)])
            main(['mine_patterns', '--state', str(state)])
            main(['build_teacher_hypotheses', '--state', str(state), '--max-hypotheses', '1',
                  '--max-patterns', '1', '--max-questions', '2', '--max-material-items', '1'])
            main(['score_teacher', '--state', str(state), '--max-concepts', '2', '--max-hypotheses', '1', '--max-evidence', '2'])
            main(['build_teacher_model', '--state', str(state)])
            main(['generate_plan', '--model', str(state.parent / 'teacher_model.json'),
                  '--materials-state', str(state), '--max-concepts', '2', '--offline'])
            plan_path = state.parent / 'current_plan.json'
            tid = read_json(plan_path)['tasks'][0]['id']
            main(['update_plan', '--plan', str(plan_path), '--event-type', 'progress',
                  '--task-id', tid, '--status', 'completed'])
        self.assertEqual(read_json(plan_path)['tasks'][0]['status'], 'completed')
        self.assertEqual(self.jev.calls, 3)

    def test_jev_rejects_invalid_numbers_legends_and_distribution(self):
        questions = {'q': {'type': 'score', 'criteria': ['a', 'b', 'c', 'd']}}
        valid = self.jev.score({}, questions)
        JevProvider.validate_response(valid, questions)
        for field, value in [('score', True), ('score', float('nan')), ('score', 4),
                             ('confidence', -1), ('legend', {'0': 'wrong'}),
                             ('probabilities', {'0': 0., '1': 0., '2': 0., '3': 0.})]:
            raw = copy.deepcopy(valid)
            raw['answers']['q'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                JevProvider.validate_response(raw, questions)


if __name__ == '__main__':
    unittest.main()
