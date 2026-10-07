"""A–I plus resume, source changes, lifecycle, integration and planner regressions."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backspace_mvp.pipeline import digest
from backspace_mvp.model import read_json
from backspace_mvp.semantic_control import SemanticControl
from backspace_mvp.teacher_update import TeacherModelUpdateEngine
from backspace_mvp.teacher_incremental import update_teacher_model, evidence_verifier
from test_integration_v07 import seed, LLMFixture, JevFixture
from backspace_mvp.hypotheses import build_teacher_hypotheses
from backspace_mvp.patterns import build_patterns
from backspace_mvp.scoring import build_teacher_scores
from backspace_mvp.teacher_model import build_teacher_model


class TeacherJev(JevFixture):
    def __init__(self):
        self.calls = 0; self.fail = False; self.relation = 'reinforces'; self.confidence = .95
        self.novel = False; self.integration = 'new_independent'; self.slow = False; self.requests = []

    def decide(self, state, questions, **kwargs):
        self.calls += 1; self.requests.append((state, questions))
        if self.fail: raise TimeoutError('fixture timeout')
        answers = {}
        existing = state.get('existing_hypotheses', [])
        for key, q in questions.items():
            kind = q['type']
            if kind == 'noul':
                flag = self.novel if key == 'novel_pattern' else self.slow if key == 'needs_slow_reasoning' else key != 'generic_subject_knowledge'
                answers[key] = {'type': kind, 'noul': .99 if flag else .01}
            elif kind == 'choice':
                option = self.relation if key == 'relation' else 'topic' if key == 'scope' else self.integration if key == 'integration' else (
                    existing[0]['id'] if existing and (not self.novel or self.integration != 'new_independent') else 'none')
                answers[key] = {'type': kind, 'choice': option, 'confidence': self.confidence,
                    'probabilities': {o: float(o == option) for o in q['criteria']}}
            else:
                score = min(3, len(q['criteria'])-1)
                answers[key] = {'type': kind, 'score': score, 'confidence': self.confidence,
                    'legend': {str(i): v for i, v in enumerate(q['criteria'])},
                    'probabilities': {str(i): float(i == score) for i in range(len(q['criteria']))}}
        return {'model': self.model, 'answers': answers, 'usage': None}


def evidence(eid='E1', source='a', kind='question'):
    quote = '조건을 비교하여 근거를 제시하시오.'
    return {'id': eid, 'kind': kind, 'origin_id': eid, 'details': {}, 'citations': [{
        'source': source, 'source_sha256': digest(source), 'locator': 'p1',
        'raw_evidence': quote, 'char_start': 0, 'char_end': len(quote)}]}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.jev = TeacherJev()
        self.scope = {'teacher_id': 'test', 'subject': 'biology'}
        self.control = SemanticControl(self.root / 'decisions', provider=self.jev)
        self.engine = TeacherModelUpdateEngine(self.root / 'model', scope=self.scope, control=self.control)
        self.engine.seed_hypothesis({'id': 'H1', 'statement': '조건 비교 후 근거 제시를 요구한다.'})
        self.generation_calls = 0

    def generate(self, *args):
        self.generation_calls += 1
        return {'id': 'HC1', 'statement': '조건 변화에 대한 예측을 요구한다.'}

    def cluster(self):
        return {'id': 'pattern1', 'pattern': {'type': 'reasoning'},
            'evidence': [evidence(), evidence('E2', 'b')], 'coverage': {'selected': 2, 'available': 2}}

    def test_a_reinforce_no_nvidia_one_batched_call(self):
        row = self.engine.update_evidence(evidence(), 'H1')
        self.assertEqual(row['relation'], 'reinforces')
        self.assertEqual(self.engine.state['hypotheses']['H1']['supporting_evidence'], ['E1'])
        self.assertEqual(self.jev.calls, 1)
        self.assertEqual(len(self.jev.requests[0][1]), 5)
        self.assertEqual(self.generation_calls, 0)

    def test_b_unrelated_is_no_change_not_counter(self):
        self.jev.relation = 'unrelated'
        before = copy.deepcopy(self.engine.state['hypotheses']['H1'])
        updates = len(self.engine.state['updates'])
        self.engine.update_evidence(evidence(), 'H1')
        self.assertEqual(before, self.engine.state['hypotheses']['H1'])
        self.assertEqual(updates, len(self.engine.state['updates']))

    def test_c_contradiction_preserves_hypothesis(self):
        self.jev.relation = 'contradicts'
        self.engine.update_evidence(evidence(), 'H1')
        h = self.engine.state['hypotheses']['H1']
        self.assertEqual(h['contradicting_evidence'], ['E1'])
        self.assertEqual(h['lifecycle_status'], 'contested')
        self.assertTrue(h['statement'])

    def test_d_scope_recorded_as_candidate(self):
        self.jev.relation = 'narrows_scope'
        before = copy.deepcopy(self.engine.state['hypotheses']['H1']['scope'])
        self.engine.update_evidence(evidence(), 'H1')
        h = self.engine.state['hypotheses']['H1']
        self.assertEqual(h['scope'], before)
        self.assertEqual(h['scope_candidates'][0]['scope'], 'topic')

    def test_e_novel_exactly_one_generation(self):
        self.jev.novel = True
        result = self.engine.process_cluster(self.cluster(), self.generate)
        self.assertEqual(result['status'], 'candidate_saved')
        self.assertEqual(self.generation_calls, 1)
        self.assertIn('HC1', self.engine.state['hypotheses'])
        self.engine.process_cluster(self.cluster(), self.generate)
        self.assertEqual(self.generation_calls, 1)

    def test_f_duplicate_does_not_create_active_hypothesis(self):
        self.jev.novel = True; self.jev.integration = 'duplicate_existing'; self.jev.slow = True
        result = self.engine.process_cluster(self.cluster(), self.generate)
        self.assertEqual(result['status'], 'duplicate_existing')
        self.assertEqual(list(self.engine.state['hypotheses']), ['H1'])

    def test_g_jev_failure_preserves_pending_evidence(self):
        self.jev.fail = True
        row = self.engine.update_evidence(evidence(), 'H1')
        self.assertEqual(row['status'], 'pending_review')
        self.assertIn('E1', self.engine.state['evidence'])
        self.assertEqual(self.engine.state['hypotheses']['H1']['supporting_evidence'], [])
        self.jev.fail = False
        row = self.engine.update_evidence(evidence(), 'H1')
        self.assertEqual(row['status'], 'applied')

    def test_h_nvidia_failure_keeps_successful_updates(self):
        self.engine.update_evidence(evidence(), 'H1'); self.jev.novel = True
        def fail(*args): raise TimeoutError('NVIDIA unavailable')
        result = self.engine.process_cluster(self.cluster(), fail)
        self.assertEqual(result['status'], 'candidate_generation_pending')
        self.assertEqual(self.engine.state['hypotheses']['H1']['supporting_evidence'], ['E1'])

    def test_i_replay_no_duplicate_delta_or_calls(self):
        self.engine.update_evidence(evidence(), 'H1')
        before = copy.deepcopy(self.engine.state); calls = self.jev.calls
        reopened = TeacherModelUpdateEngine(self.root / 'model', scope=self.scope, control=self.control)
        reopened.update_evidence(evidence(), 'H1')
        self.assertEqual(reopened.state, before); self.assertEqual(calls, self.jev.calls)

    def test_low_confidence_pending_not_unrelated(self):
        self.jev.confidence = .1
        row = self.engine.update_evidence(evidence(), 'H1')
        self.assertEqual(row['status'], 'pending_review'); self.assertEqual(row['relation'], 'insufficient')

    def test_source_removal_and_body_change_invalidate_support(self):
        self.engine.update_evidence(evidence(), 'H1')
        self.engine.reconcile_evidence({})
        self.assertEqual(self.engine.state['hypotheses']['H1']['statistics']['support_count'], 0)
        self.assertEqual(len(self.engine.state['relations']), 1)

    def test_source_diversity_and_coverage_required_for_promotion(self):
        self.engine.update_evidence(evidence(), 'H1')
        self.engine.update_evidence(evidence('E2'), 'H1')
        self.assertFalse(self.engine.stabilize('H1', coverage=1))
        self.engine.update_evidence(evidence('E3', 'b'), 'H1')
        self.assertFalse(self.engine.stabilize('H1', coverage=.5))
        self.assertTrue(self.engine.stabilize('H1', coverage=1))

    def test_feedback_append_and_replay_do_not_replace_jev(self):
        self.engine.update_evidence(evidence(), 'H1')
        relation = copy.deepcopy(self.engine.state['relations'])
        self.engine.record_feedback('H1', 'human_rejected', reason='원문과 해석 불일치', event_id='feedback1')
        self.engine.record_feedback('H1', 'human_rejected', reason='원문과 해석 불일치', event_id='feedback1')
        self.assertEqual(len(self.engine.state['feedback']), 1)
        self.assertEqual(self.engine.state['relations'], relation)
        self.assertEqual(self.engine.state['hypotheses']['H1']['lifecycle_status'], 'rejected')

    def test_atomic_checkpoint_repairs_partial_projection(self):
        self.engine.update_evidence(evidence(), 'H1')
        path = self.root / 'model/hypotheses/H1.json'; path.unlink()
        reopened = TeacherModelUpdateEngine(self.root / 'model', scope=self.scope, control=self.control)
        with reopened.transaction(): pass
        self.assertEqual(read_json(path), reopened.state['hypotheses']['H1'])

    def test_corruption_not_silently_rebuilt(self):
        path = self.root / 'model/state.json'; value = read_json(path); value['version'] = 999
        path.write_text(__import__('json').dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '손상'):
            TeacherModelUpdateEngine(self.root / 'model', scope=self.scope, control=self.control)

    def test_provenance_quote_validation(self):
        e = evidence(); source = {'id': 'a', 'sha256': digest('a'),
            'excerpts': [{'locator': 'p1', 'text': e['citations'][0]['raw_evidence']}]}
        verify = evidence_verifier({'sources': [source]}); verify(e)
        e['citations'][0]['raw_evidence'] = '원문에 없는 문장'
        with self.assertRaises(ValueError): verify(e)

    def test_default_orchestrator_keeps_legacy_model_and_planner_contract(self):
        state = seed(self.root / 'workflow'); build_patterns(state)
        llm = LLMFixture(); build_teacher_hypotheses(state, provider=llm, max_patterns=1, max_questions=2)
        build_teacher_scores(state, provider=self.jev, max_concepts=2); previous = build_teacher_model(state)
        with patch('backspace_mvp.teacher_incremental.retrieve_memory', return_value={'notes': [], 'selected': 0, 'eligible': 0}):
            result = update_teacher_model(state, provider=llm, jev_provider=self.jev, max_concepts=2)
            calls = llm.calls
            again = update_teacher_model(state, provider=llm, jev_provider=self.jev, max_concepts=2)
        self.assertEqual(llm.calls, calls)
        self.assertEqual(result['assessment_ideals'][0]['statement'], previous['assessment_ideals'][0]['statement'])
        self.assertIn('incremental', again)
        self.assertEqual(result['incremental']['state_version'], again['incremental']['state_version'])
        self.assertTrue((state.parent / 'teacher_model/updates').exists())
        from backspace_mvp.study_plan import generate_study_plan
        plan = generate_study_plan(state.parent / 'teacher_model.json', state, offline=True, max_concepts=2)
        self.assertTrue(plan['tasks'])

    def test_default_new_model_failure_is_pending_not_failed(self):
        state = seed(self.root / 'new'); build_patterns(state); self.jev.novel = True
        llm = LLMFixture()
        with patch('backspace_mvp.teacher_incremental.retrieve_memory', return_value={'notes': []}), \
             patch.object(llm, 'complete', side_effect=TimeoutError('offline')):
            result = update_teacher_model(state, provider=llm, jev_provider=self.jev, max_concepts=2)
        self.assertGreater(result['incremental']['candidate_generation_pending'], 0)
        self.assertEqual(result['assessment_ideals'], [])

    def test_pattern_membership_is_not_a_new_source_observation(self):
        original = evidence(); original['details']['matching_pattern_ids'] = ['P1', 'P2']
        self.engine.update_evidence(original, 'H1'); calls = self.jev.calls
        selected = copy.deepcopy(original); selected['details']['matching_pattern_ids'] = ['P1']
        self.engine.update_evidence(selected, 'H1')
        self.assertEqual(self.jev.calls, calls)
        self.assertEqual(self.engine.state['hypotheses']['H1']['statistics']['support_count'], 1)

    def test_integration_failure_resumes_without_second_nvidia_call(self):
        self.jev.novel = True
        original = self.jev.decide
        def fail_integration(state, questions, **kwargs):
            if 'integration' in questions: raise TimeoutError('integration unavailable')
            return original(state, questions, **kwargs)
        with patch.object(self.jev, 'decide', side_effect=fail_integration):
            result = self.engine.process_cluster(self.cluster(), self.generate)
        self.assertEqual(result['status'], 'integration_pending')
        self.engine.process_cluster(self.cluster(), self.generate)
        self.assertEqual(self.generation_calls, 1)
        self.assertIn('HC1', self.engine.state['hypotheses'])

    def test_material_only_new_workspace_still_saves_model_and_state(self):
        from backspace_mvp.pipeline import save
        from backspace_mvp.question_graphs import export_question_graphs
        state = seed(self.root / 'materials'); data = read_json(state)
        data['questions'] = []; save(state, data); export_question_graphs(data, state.parent / 'question_graphs')
        build_patterns(state)
        with patch('backspace_mvp.teacher_incremental.retrieve_memory', return_value={'notes': []}):
            result = update_teacher_model(state, jev_provider=self.jev, max_concepts=2)
        self.assertEqual(result['assessment_ideals'], [])
        self.assertTrue((state.parent / 'teacher_model/state.json').exists())
        self.assertEqual(result['counts']['questions'], 0)

    def test_retrieval_omissions_cannot_be_hidden_on_replay(self):
        self.engine.update_evidence(evidence(), 'H1', coverage={'hypotheses_selected': 1, 'hypotheses_available': 3})
        self.engine.update_evidence(evidence('E2', 'b'), 'H1')
        self.assertFalse(self.engine.stabilize('H1', coverage=1))
        self.assertEqual(self.engine.state['hypotheses']['H1']['lifecycle_status'], 'candidate')

    def test_partial_projection_invalid_json_is_repaired(self):
        self.engine.update_evidence(evidence(), 'H1')
        path = self.root / 'model/hypotheses/H1.json'; path.write_text('{', encoding='utf-8')
        with self.engine.transaction(): pass
        self.assertEqual(read_json(path), self.engine.state['hypotheses']['H1'])


if __name__ == '__main__': unittest.main()
