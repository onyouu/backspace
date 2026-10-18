"""Shared evidence gate, audit preservation and incremental replay regressions."""
import copy
import unittest

import test_teacher_update as fixtures
from backspace_mvp.teacher_update import TeacherModelUpdateEngine
from backspace_mvp.pipeline import digest, save
from backspace_mvp.model import read_json


class TeacherPrefilterTests(unittest.TestCase):
    setUp = fixtures.UpdateTests.setUp

    def generic(self):
        decide = self.jev.decide

        def generic_decide(state, questions, **kwargs):
            result = decide(state, questions, **kwargs)
            if 'teacher_signal' in questions:
                result['answers']['teacher_signal']['noul'] = .01
                result['answers']['generic_subject_knowledge']['noul'] = .99
            return result
        self.jev.decide = generic_decide

    def test_generic_preserved_no_relation_or_hypothesis_change_and_replay_cached(self):
        self.generic()
        e = fixtures.evidence(kind='material_concept')
        before = copy.deepcopy(self.engine.state['hypotheses'])
        result = self.engine.update_related_evidence(e, ['H1'])
        self.assertEqual(result['status'], 'generic_evidence_preserved')
        self.assertEqual(self.engine.state['hypotheses'], before)
        self.assertEqual(self.engine.state['relations'], {})
        self.assertIn('E1', self.engine.state['evidence'])
        self.assertEqual(result['provenance'], e['citations'])
        self.assertEqual(self.jev.calls, 1)
        reopened = TeacherModelUpdateEngine(self.engine.folder, scope=self.scope, control=self.control)
        reopened.update_related_evidence(e, ['H1'])
        self.assertEqual(self.jev.calls, 1)
        self.assertTrue((self.engine.folder / 'prefilters' / (result['id'] + '.json')).exists())

    def test_signal_uses_one_shared_gate_for_multiple_hypotheses(self):
        self.engine.seed_hypothesis({'id': 'H2', 'statement': '다른 잠정 가설'})
        self.engine.update_related_evidence(fixtures.evidence(), ['H1', 'H2'])
        self.assertEqual(self.jev.calls, 3)
        self.assertEqual(len(self.jev.requests[0][0]['existing_hypotheses']), 2)
        self.assertEqual(len(self.engine.state['relations']), 2)

    def test_gate_failure_pending_no_fake_unrelated_and_retry(self):
        self.jev.fail = True
        result = self.engine.update_related_evidence(fixtures.evidence(kind='material_concept'), ['H1'])
        self.assertEqual(result['status'], 'pending_review')
        self.assertFalse(self.engine.state['relations'])
        self.jev.fail = False
        result = self.engine.update_related_evidence(fixtures.evidence(kind='material_concept'), ['H1'])
        self.assertEqual(result['status'], 'applied')
        self.assertTrue(self.engine.state['pending'][result['id']]['resolved'])

    def test_generic_uncertainty_does_not_veto_clear_teacher_signal(self):
        decide = self.jev.decide
        def uncertain_generic(state, questions, **kwargs):
            result = decide(state, questions, **kwargs)
            if 'generic_subject_knowledge' in questions:
                result['answers']['generic_subject_knowledge']['noul'] = .5
            return result
        self.jev.decide = uncertain_generic
        result = self.engine.update_related_evidence(fixtures.evidence(kind='material_concept'), ['H1'])
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(self.jev.calls, 2)

    def test_ambiguous_gate_keeps_pending(self):
        decide = self.jev.decide
        def ambiguous(state, questions, **kwargs):
            result = decide(state, questions, **kwargs)
            if 'teacher_signal' in questions: result['answers']['teacher_signal']['noul'] = .5
            return result
        self.jev.decide = ambiguous
        result = self.engine.update_related_evidence(fixtures.evidence(kind='material_concept'), ['H1'])
        self.assertEqual(result['status'], 'pending_review')
        self.assertFalse(self.engine.state['relations'])

    def test_actual_question_cannot_be_filtered_as_generic(self):
        self.generic()
        self.engine.update_related_evidence(fixtures.evidence(), ['H1'])
        self.assertEqual(len(self.engine.state['relations']), 1)
        self.assertEqual(self.jev.calls, 2)

    def test_known_counter_cannot_be_filtered_as_generic(self):
        e = fixtures.evidence(kind='material_concept')
        self.jev.relation = 'contradicts'
        self.engine.update_evidence(e, 'H1')
        self.generic()
        self.assertFalse(self.engine.generic_evidence_processed(e, ['H1']))
        result = self.engine.update_related_evidence(e, ['H1'])
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(self.engine.state['hypotheses']['H1']['lifecycle_status'], 'contested')

    def test_changed_hypothesis_or_source_requires_new_gate(self):
        self.generic()
        e = fixtures.evidence(kind='material_concept')
        self.engine.update_related_evidence(e, ['H1'])
        changed = fixtures.evidence(source='b', kind='material_concept')
        self.assertFalse(self.engine.generic_evidence_processed(changed, ['H1']))
        with self.engine.transaction():
            self.engine.state['hypotheses']['H1']['statement'] = '수정된 가설 문장'
            self.assertFalse(self.engine.generic_evidence_processed(e, ['H1']))

    def test_old_checkpoint_can_add_prefilter_without_changing_existing_decisions(self):
        self.engine.update_evidence(fixtures.evidence(), 'H1')
        old = read_json(self.engine.folder / 'state.json')
        old.pop('prefilters', None); old.pop('state_hash')
        old['state_hash'] = digest(old)
        save(self.engine.folder / 'state.json', old)
        reopened = TeacherModelUpdateEngine(self.engine.folder, scope=self.scope, control=self.control)
        before = copy.deepcopy(reopened.state['relations'])
        with reopened.transaction(): reopened._commit()
        self.assertEqual(reopened.state['relations'], before)
        self.assertEqual(reopened.state['question_versions'], old['question_versions'])

    def test_obsolete_incomplete_retrieval_does_not_block_current_support(self):
        self.engine.update_evidence(fixtures.evidence(), 'H1', coverage={
            'hypotheses_selected': 1, 'hypotheses_available': 4})
        self.engine.update_evidence(fixtures.evidence(source='c'), 'H1', coverage={
            'hypotheses_selected': 1, 'hypotheses_available': 1})
        self.engine.update_evidence(fixtures.evidence('E2', 'b'), 'H1')
        self.assertTrue(self.engine.stabilize('H1', coverage=1))
