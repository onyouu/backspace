import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backspace_mvp.model import read_json
from backspace_mvp.pipeline import save
from backspace_mvp.patterns import build_patterns
from backspace_mvp.hypotheses import build_teacher_hypotheses
from backspace_mvp.scoring import build_teacher_scores
from backspace_mvp.teacher_model import build_teacher_model
from backspace_mvp.study_plan import _teacher_context
from backspace_mvp.web import WebStore
from test_integration_v07 import seed, LLMFixture, JevFixture


class PlanWorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.guard = patch('urllib.request.urlopen', side_effect=AssertionError('No network'))
        self.guard.start(); self.addCleanup(self.guard.stop)
        self.store = WebStore(storage=Path(tmp.name))
        state = seed(self.store.workspace / 'teacher')
        self.llm, self.jev = LLMFixture(), JevFixture()
        build_patterns(state)
        build_teacher_hypotheses(state, provider=self.llm, max_hypotheses=1, max_patterns=1, max_questions=2, max_material_items=1)
        build_teacher_scores(state, provider=self.jev, max_concepts=2, max_hypotheses=1, max_evidence=2)
        build_teacher_model(state)
        self.teacher_before = (self.store.workspace / 'teacher/teacher_model.json').read_bytes()

    def run_plan(self, **kw):
        options = {'mode': 'workspace', 'offline': True, 'materials_origin': 'teacher', 'max_concepts': 2, **kw}
        job = self.store.start('plan', options)
        end = time.monotonic() + 15
        while self.store.active and time.monotonic() < end:
            time.sleep(.02)
        result = self.store.jobs[job['id']]
        self.assertEqual(result['status'], 'done', result.get('error'))
        self.assertEqual(result['outcome'], 'complete')
        return read_json(self.store.workspace / 'current_plan.json')

    def test_teacher_range_without_reupload_and_a_b_a_selection(self):
        self.run_plan(days=1)
        self.run_plan(days=2)
        plan = self.run_plan(days=1)
        self.assertEqual(plan['parameters']['days'], 1)
        self.assertEqual(plan['parameters']['materials_origin'], 'teacher')
        self.assertFalse((self.store.workspace / 'scope/dataset.json').exists())
        self.assertFalse(self.store.data('workspace')['plan_stale'])
        self.assertEqual(self.teacher_before, (self.store.workspace / 'teacher/teacher_model.json').read_bytes())
        task = plan['tasks'][0]['id']
        self.store.update_plan({'mode': 'workspace', 'event_type': 'progress', 'task_id': task, 'status': 'completed'})
        replay = self.run_plan(days=1)
        self.assertEqual(next(t for t in replay['tasks'] if t['id'] == task)['status'], 'completed')

    def test_note_remains_pending_offline_then_reflected_online_without_teacher_rebuild(self):
        self.run_plan()
        self.store.update_plan({'mode': 'workspace', 'event_type': 'constraint', 'note': 'Include citations in activities'})
        pending = self.run_plan()
        self.assertTrue(pending['needs_revision'])
        with patch('backspace_mvp.llm_provider.create_provider', return_value=self.llm), \
             patch('backspace_mvp.study_plan.JevProvider', wraps=JevFixture) as provider:
            # Keep the real response validator while replacing only construction.
            from backspace_mvp.jev import JevProvider
            provider.side_effect = lambda **kw: self.jev
            provider.validate_response = JevProvider.validate_response
            reflected = self.run_plan(offline=False)
            calls = self.llm.calls, self.jev.calls
            self.run_plan(offline=False)
            self.assertEqual(calls, (self.llm.calls, self.jev.calls))
        self.assertFalse(reflected['needs_revision'])
        self.assertIn(pending['events'][-1]['id'], reflected['processed_event_ids'])
        self.assertEqual(self.teacher_before, (self.store.workspace / 'teacher/teacher_model.json').read_bytes())

    def test_invalid_range_preserves_saved_plan(self):
        self.run_plan()
        before = (self.store.workspace / 'current_plan.json').read_bytes()
        job = self.store.start('plan', {'mode': 'workspace', 'materials_origin': 'scope'})
        end = time.monotonic() + 15
        while self.store.active and time.monotonic() < end: time.sleep(.02)
        self.assertEqual(self.store.jobs[job['id']]['status'], 'failed')
        self.assertEqual(before, (self.store.workspace / 'current_plan.json').read_bytes())

    def test_conditional_candidates_used_only_for_relevant_concepts(self):
        model = read_json(self.store.workspace / 'teacher/teacher_model.json')
        candidate = model['assessment_ideals'][0]
        candidate.update(statement='Operon conditions should be connected', lifecycle_status='candidate', readiness='needs_review')
        candidate['applicable_context']['concept_ids'] = []
        candidate['applicable_context']['conditions'] = ['Operon explanation only']
        selected = _teacher_context(model, {'id': 'new', 'label': 'Operon', 'aliases': []}, [], {})
        self.assertIn(candidate['id'], selected['selected_ideal_ids'])
        unrelated = _teacher_context(model, {'id': 'new', 'label': 'UnrelatedUnique', 'aliases': []}, [], {})
        self.assertNotIn(candidate['id'], unrelated['selected_ideal_ids'])
        self.assertEqual(candidate['readiness'], 'needs_review')


if __name__ == '__main__':
    unittest.main()
