import copy
import json
import tempfile
import unittest
from pathlib import Path

from backspace_mvp.analysis import analyze
from backspace_mvp.model import read_json, validate
from backspace_mvp.pipeline import empty_dataset, read_source, save, ingest, build, generate_plan
from backspace_mvp.retrieval import retrieve
from test_staged import Fixture, QUESTION


def input_data(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('\n입력:\n')[1])[0]


class GroundedTests(unittest.TestCase):
    def setup_files(self, folder):
        root = Path(folder)
        exam = root / 'exam.txt'
        exam.write_text(QUESTION, encoding='utf-8')
        return root, exam, root / 'state.json'

    def test_actual_material_text_reaches_analysis_not_only_names(self):
        class Observer(Fixture):
            context = None
            def complete(self, prompt, schema):
                if 'steps' in schema['properties']:
                    self.context = input_data(prompt)['material_blocks']
                return super().complete(prompt, schema)
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            material = root / 'lesson.txt'
            material.write_text('산소는 전자 전달계의 최종 전자 수용체이다.', encoding='utf-8')
            provider = Observer()
            ingest(state, material, 'learning_material', provider=provider)
            data = ingest(state, exam, 'exam', 'e', provider)
            self.assertIn('최종 전자 수용체', provider.context[0]['text'])
            self.assertEqual(data['questions'][0]['retrieval']['selected_blocks'], provider.context)
            self.assertEqual(data['questions'][0]['claims'][0]['review_status'], 'supported')

    def test_retrieval_respects_budget_and_original_offsets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            material = root / 'lesson.txt'
            material.write_text('산소는 전자 전달계의 최종 전자 수용체이다.\nATP 합성에는 양성자 기울기가 필요하다.', encoding='utf-8')
            data = empty_dataset()
            data['sources'] = [read_source(material, 'learning_material')]
            full = retrieve(data, '산소와 ATP 생성')
            self.assertTrue(full['selected_blocks'])
            tiny = retrieve(data, '산소와 ATP 생성', max_chars=10)
            self.assertEqual(tiny['selected_blocks'], [])
            self.assertTrue(tiny['budget_limited'])
            text = data['sources'][0]['excerpts'][0]['text']
            for b in full['selected_blocks']:
                self.assertEqual(text[b['start']:b['end']], b['text'])

    def test_correct_quote_cannot_bypass_relation_semantic_rejection(self):
        class WrongRelation(Fixture):
            def complete(self, prompt, schema):
                if 'verdicts' in schema['properties']:
                    self.calls += 1
                    return {'verdicts': [{'index': 0, 'status': 'contradicted', 'reason': '원문은 구성 부분 관계를 말하지 않는다.'}]}
                result = super().complete(prompt, schema)
                if 'relations' in result:
                    result = {'concepts': [{'label': s, 'surface_form': s, 'quote': '산소는 최종 전자 수용체이다.',
                        'confidence': 0.8, 'explicit_emphasis': []} for s in ['산소', '최종 전자 수용체']], 'relations': [{
                        'from_label': '산소', 'to_label': '최종 전자 수용체', 'relation': 'part_of',
                        'statement': '산소는 최종 전자 수용체의 구성 부분이다.', 'conditions': [], 'confidence': 0.8,
                        'quote': '산소는 최종 전자 수용체이다.'}]}
                return result
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            material = root / 'lesson.txt'
            material.write_text('산소는 최종 전자 수용체이다.', encoding='utf-8')
            data = ingest(root / 'state.json', material, 'learning_material', provider=WrongRelation())
            self.assertEqual(data['material_relations'], [])
            manifest = read_json(next((root / 'checkpoints').glob('*/manifest.json')))
            self.assertEqual(manifest['semantic_reviews'][0]['review']['verdicts'][0]['status'], 'contradicted')

    def test_uncited_claim_stays_provisional_even_if_reviewer_says_supported(self):
        class Uncited(Fixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'steps' in value:
                    value['claims'][0]['references'] = []
                return value
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            data = ingest(state, exam, 'exam', 'e', Uncited())
            q = data['questions'][0]
            self.assertEqual(q['analysis_status'], 'needs_reference_review')
            self.assertEqual(q['claims'][0]['review_status'], 'domain_knowledge_needs_review')
            model = root / 'model.json'
            build(state, model)
            plan = generate_plan(model, root / 'plan.json')
            self.assertTrue(all(t['review_status'] == 'needs_reference_review' for t in plan['tasks']))
            tampered = copy.deepcopy(data)
            tampered['questions'][0]['claims'][0]['review_status'] = 'supported'
            with self.assertRaisesRegex(ValueError, 'uncited claim'):
                validate(tampered)

    def test_grounding_check_downgrades_a_plausible_mechanism_not_in_quote(self):
        class UnsupportedMechanism(Fixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'steps' in value:
                    value['claims'][0]['statement'] = '전자 전달의 감소는 양성자 기울기를 약화시킨다.'
                if 'verdicts' in value:
                    value['verdicts'][0] = {'index': 0, 'status': 'domain_knowledge_needs_review',
                        'reason': '인용에는 양성자 기울기 기작이 제시되지 않았다.'}
                return value
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            q = ingest(state, exam, 'exam', 'e', UnsupportedMechanism())['questions'][0]
            self.assertEqual(q['analysis_status'], 'needs_reference_review')
            self.assertEqual(q['claims'][0]['evidence'], [])
            self.assertEqual(q['review_history'][-1]['grounding_verdicts'][0]['status'], 'domain_knowledge_needs_review')

    def test_semantic_failure_preserves_state_after_bounded_revision(self):
        class Reject(Fixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'claim_verdicts' in value:
                    value['claim_verdicts'][0] = {'index': 0, 'status': 'contradicted', 'reason': '검수용 과학 오류'}
                return value
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            save(state, empty_dataset())
            before = state.read_bytes()
            provider = Reject()
            with self.assertRaisesRegex(ValueError, '의미 검토'):
                ingest(state, exam, 'exam', 'e', provider)
            self.assertEqual(state.read_bytes(), before)
            self.assertEqual(provider.calls, 5)  # Identical rejected revision reuses both reviews.
            manifest = read_json(next((root / 'checkpoints').glob('*/manifest.json')))
            self.assertEqual(len(manifest['semantic_reviews'][0]['history']), 2)

    def test_semantic_revision_and_second_review_are_recorded(self):
        class Revise(Fixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'steps' in value and '기존 결과의 구체적인 오류를 수정' in prompt:
                    value['steps'][0]['label'] = '산소 조작 조건과 ATP 관찰값 구분'
                if 'claim_verdicts' in value:
                    candidate = input_data(prompt)['analysis']
                    if candidate['steps'][0]['label'] == '산소 조건 비교':
                        value['step_verdicts'][0] = {'index': 0, 'status': 'contradicted', 'reason': '조건과 관찰을 구분하는 목표로 고칠 것'}
                return value
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            q = ingest(state, exam, 'exam', 'e', Revise())['questions'][0]
            self.assertEqual(len(q['review_history']), 2)
            self.assertEqual(q['steps'][0]['label'], '산소 조작 조건과 ATP 관찰값 구분')

    def test_concept_alignment_only_uses_linked_steps(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            data = ingest(state, exam, 'exam', 'e', Fixture())
            report = analyze(data)[0]
            self.assertEqual(report['concept_alignment'][0]['reasoning_codes'], ['compare'])
            graph = next(iter(report['graphs']['questions'].values()))
            self.assertTrue(any('expected' in n.get('output', '') or 'ATP' in n.get('output', '') for n in graph['nodes']))

    def test_tasks_are_distinct_and_completion_resets_when_assignment_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            ingest(state, exam, 'exam', 'e', Fixture())
            model, output = root / 'model.json', root / 'plan.json'
            build(state, model)
            plan = generate_plan(model, output)
            self.assertNotEqual(plan['tasks'][0]['activity'], plan['tasks'][1]['activity'])
            self.assertTrue(plan['tasks'][0]['success_criteria'])
            plan['tasks'][0]['status'] = 'completed'
            save(output, plan)
            self.assertEqual(generate_plan(model, output)['tasks'][0]['status'], 'completed')
            report = read_json(model)
            report['questions'][0]['steps'][0]['success_criteria'].append('ATP 변화와 인과 해석 구별')
            save(model, report)
            updated = generate_plan(model, output)
            self.assertEqual(updated['tasks'][0]['status'], 'pending')
            self.assertEqual(updated['student_observation'], 'not_observed')
            self.assertEqual(len(list((root / 'plan_history').glob('*.json'))), 2)

    def test_refresh_replaces_existing_analysis_without_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            ingest(state, exam, 'exam', 'e', Fixture())
            data = ingest(state, exam, 'exam', 'e', Fixture(), refresh=True)
            self.assertEqual(len(data['questions']), 1)
            self.assertEqual(len(data['sources']), 1)

    def test_retrieved_text_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            material = root / 'lesson.txt'
            material.write_text('산소와 ATP 생성은 연결된다.', encoding='utf-8')
            ingest(state, material, 'learning_material', provider=Fixture())
            data = ingest(state, exam, 'exam', 'e', Fixture())
            data['questions'][0]['retrieval']['selected_blocks'][0]['text'] = '조작된 자료'
            with self.assertRaisesRegex(ValueError, 'original substring'):
                validate(data)

    def test_step_cannot_introduce_an_unaudited_answer_statement(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            data = ingest(state, exam, 'exam', 'e', Fixture())
            q = data['questions'][0]
            audits = [c for c in q['claims'] if c['origin'] == 'step_output']
            self.assertEqual(len(audits), len(q['steps']))
            q['steps'][0]['output'] = '검토되지 않은 다른 과학적 답안'
            with self.assertRaisesRegex(ValueError, 'audited claim'):
                validate(data)

    def test_grounding_failure_cannot_be_hidden_by_generic_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, state = self.setup_files(folder)
            data = ingest(state, exam, 'exam', 'e', Fixture())
            q = data['questions'][0]
            q['review_history'][-1]['grounding_verdicts'][0]['status'] = 'domain_knowledge_needs_review'
            with self.assertRaisesRegex(ValueError, 'cannot be promoted'):
                validate(data)
