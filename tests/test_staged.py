import tempfile
import json
import unittest
from pathlib import Path
from backspace_mvp.pipeline import ingest, build, generate_plan, save, empty_dataset
from backspace_mvp.model import read_json


QUESTION = '1. 산소 공급이 감소하면 산화적 인산화에 의한 ATP 생성이 감소할 수 있다. 설명하시오.'


class Fixture:
    def __init__(self, bad_quote=False):
        self.calls = 0
        self.bad_quote = bad_quote

    def complete(self, prompt, schema):
        self.calls += 1
        if 'relations' in schema['properties']:
            source_text = json.JSONDecoder().raw_decode(prompt.split('\n', 1)[1])[0]['text']
            return {'concepts': [{'label': '산소', 'surface_form': '산소',
                'quote': source_text, 'confidence': 0.8, 'explicit_emphasis': []}], 'relations': []}
        if 'questions' in schema['properties']:
            return {'questions': [{'number': '1', 'text': QUESTION, 'context': '', 'complete': True}]}
        if 'verdicts' in schema['properties']:
            claims = json.JSONDecoder().raw_decode(prompt.split('\n입력:\n')[1])[0]['claims']
            return {'verdicts': [{'index': i, 'status': 'supported', 'reason': '검증용 근거 판정'} for i in range(len(claims))]}
        if 'claim_verdicts' in schema['properties']:
            analysis = json.JSONDecoder().raw_decode(prompt.split('\n입력:\n')[1])[0]['analysis']
            def verdicts(field):
                return [{'index': i, 'status': 'supported', 'reason': '검증용 고정 판정'} for i in range(len(analysis[field]))]
            return {'task_verdicts': [{'index': 0, 'status': 'supported', 'reason': '문항 요구에 근거한 과제'}],
                'claim_verdicts': verdicts('claims'), 'step_verdicts': verdicts('steps'),
                'link_verdicts': verdicts('links'), 'missing_requirements': [], 'issues': []}
        return {'task': {'description': '산소 감소와 ATP 생성 변화를 설명한다.', 'quote': QUESTION, 'confidence': 0.8},
            'confidence': 0.8, 'concepts': [{'label': '산소', 'step': 0, 'confidence': 0.8}],
            'steps': [{'code': 'compare', 'label': '산소 조건 비교', 'input': '산소 감소 조건',
                       'output': '산소 변화와 ATP 생성의 비교표', 'success_criteria': ['원인 조건과 관찰 결과 구분'],
                       'conditions': [], 'practice': '산소 공급 조건과 ATP 생성량을 두 열로 구분한 표를 작성하세요.',
                       'claim_indices': [0], 'criterion_references': [{'block_id': 'question', 'quote': QUESTION}], 'confidence': 0.8},
                      {'code': 'justify', 'label': 'ATP 감소 설명', 'input': '조건 비교표',
                       'output': 'ATP 감소를 조건과 연결한 답안', 'success_criteria': ['산소 감소와 ATP 생성 감소 연결'],
                       'conditions': ['전자 전달의 완전 중단을 단정하지 않음'],
                       'practice': '산소 공급 감소와 ATP 생성 감소를 연결하는 조건부 설명을 작성하세요.',
                       'claim_indices': [0], 'criterion_references': [{'block_id': 'question', 'quote': QUESTION}], 'confidence': 0.8}],
            'claims': [{'statement': '산소 공급 감소 조건이 주어졌다.', 'conditions': [], 'confidence': 0.8,
                        'references': [{'block_id': 'question', 'quote': '다른 문항 인용' if self.bad_quote else '산소 공급이 감소하면'}]}],
            'answer_requirements': ['산소 변화와 ATP 감소의 조건부 연결'],
            'links': [{'from': 0, 'to': 1, 'relation': 'supports', 'explanation': '조건 비교가 결과 설명의 근거가 된다.'}],
            'intent': {'objective': '기작 연결을 평가한다는 가설', 'success_criteria': ['산소 역할을 설명'], 'confidence': 0.8}}


class StagedTests(unittest.TestCase):
    def test_semantic_repair_is_bounded_and_checked(self):
        class Repair(Fixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'steps' in value and '검증 오류:' not in prompt:
                    value['concepts'][0]['step'] = 2
                return value
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exam = root / 'exam.txt'
            exam.write_text(QUESTION, encoding='utf-8')
            provider = Repair()
            result = ingest(root / 'state.json', exam, 'exam', 'e1', provider)
            self.assertEqual(provider.calls, 5)
            self.assertEqual(len(result['questions']), 1)
            self.assertEqual(len(list((root / 'checkpoints').glob('*/*.failed-0.json'))), 1)
    def test_live_shape_full_flow_and_shared_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            material, exam, state = [root / x for x in ('material.txt', 'exam.txt', 'state.json')]
            material.write_text('산소는 최종 전자 수용체이다.', encoding='utf-8')
            exam.write_text(QUESTION, encoding='utf-8')
            provider = Fixture()
            ingest(state, material, 'learning_material', provider=provider)
            result = ingest(state, exam, 'exam', 'e1', provider)
            self.assertEqual(provider.calls, 5)
            self.assertEqual(len(result['concepts']), 1)
            q = result['questions'][0]
            self.assertEqual(q['concept_ids'], [result['concepts'][0]['id']])
            self.assertEqual(q['steps'][0]['id'], 's0')
            model, plan = root / 'model.json', root / 'plan.json'
            self.assertEqual(build(state, model)['counts']['questions'], 1)
            self.assertTrue(generate_plan(model, plan)['tasks'])

    def test_failure_preserves_state_and_resumes_valid_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exam, state = root / 'exam.txt', root / 'state.json'
            exam.write_text(QUESTION, encoding='utf-8')
            save(state, empty_dataset())
            before = state.read_bytes()
            failing = Fixture(bad_quote=True)
            with self.assertRaises(ValueError):
                ingest(state, exam, 'exam', 'e1', failing)
            self.assertEqual(before, state.read_bytes())
            retry = Fixture()
            ingest(state, exam, 'exam', 'e1', retry)
            self.assertEqual(retry.calls, 3)  # Segmentation reused; analysis, meaning review and grounding run.
            manifests = list((root / 'checkpoints').glob('*/manifest.json'))
            self.assertTrue(read_json(manifests[0])['stages'][0]['cached'])

    def test_unlinked_steps_rejected(self):
        class Unlinked(Fixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'steps' in value:
                    value['links'] = []
                return value
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exam = root / 'exam.txt'
            exam.write_text(QUESTION, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '연결되지 않은'):
                ingest(root / 'state.json', exam, 'exam', 'e1', Unlinked())

    def test_incomplete_question_not_persisted(self):
        class Incomplete(Fixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'questions' in value:
                    value['questions'][0]['complete'] = False
                return value
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exam = root / 'exam.txt'
            exam.write_text(QUESTION, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '불완전한'):
                ingest(root / 'state.json', exam, 'exam', 'e1', Incomplete())
            self.assertFalse((root / 'state.json').exists())
