import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from jsonschema import ValidationError
from backspace_mvp.model import read_json, validate
from backspace_mvp.pipeline import ingest, save
from backspace_mvp.question_graphs import export_question_graphs, validate_question_graph
from test_staged import Fixture


EXAM = '1. 산소 조건을 비교하고 ATP 변화를 설명하시오.\n2. 산소 감소만으로 전체 ATP 생성 중단을 단정할 수 있는가?'


class QuestionFixture(Fixture):
    """Structural fixture for provenance/isolation tests, not a scientific benchmark."""
    inputs = []

    def __init__(self):
        super().__init__()
        self.inputs = []

    def complete(self, prompt, schema):
        if 'questions' in schema['properties']:
            self.calls += 1
            text = prompt.split('원문:\n', 1)[1].split('\n검증 오류:', 1)[0]
            lines = [s for s in text.splitlines() if re.match(r'^\d+\.', s)]
            return {'questions': [{'number': s.split('.', 1)[0], 'text': s, 'context': '', 'complete': True} for s in lines]}
        if 'steps' not in schema['properties']:
            return super().complete(prompt, schema)
        inputs = json.JSONDecoder().raw_decode(prompt.split('\n입력:\n', 1)[1])[0]
        self.inputs.append(inputs)
        value = super().complete(prompt, schema)
        question = inputs['question']
        value['task'] = {'description': question, 'quote': question, 'confidence': 0.8}
        value['claims'][0]['statement'] = question
        value['claims'][0]['references'] = [{'block_id': 'question', 'quote': question}]
        for step in value['steps']:
            step['criterion_references'] = [{'block_id': b['block_id'], 'quote': b['text']} for b in inputs['answer_key_blocks']]
            if not step['criterion_references']:
                step['criterion_references'] = [{'block_id': 'question', 'quote': question}]
        # Deliberate branching in Q1; the exporter must retain it rather than make a chain.
        if question.startswith('1.'):
            third = copy.deepcopy(value['steps'][1])
            third.update(code='predict', label='조건 변화 예측', output='조건별 결과 예측표')
            value['steps'].append(third)
            value['links'].append({'from': 0, 'to': 2, 'relation': 'supports', 'explanation': '조건 비교가 결과 예측의 근거이다.'})
        if inputs['answer_key_blocks']:
            key = inputs['answer_key_blocks'][0]
            value['claims'][0].update(statement=key['text'], references=[{'block_id': key['block_id'], 'quote': key['text']}])
        return value


class QuestionGraphTests(unittest.TestCase):
    def setup_files(self, folder):
        root = Path(folder)
        exam = root / 'exam.txt'
        exam.write_text(EXAM, encoding='utf-8')
        answers = root / 'answers.txt'
        answers.write_text('1. 산소는 최종 전자 수용체이다.\n2. 전체 ATP 생성 중단은 이 관찰만으로 단정할 수 없다.', encoding='utf-8')
        manifest = root / 'answer_key.json'
        save(manifest, {'schema_version': '1.0', 'exam_id': 'e', 'entries': [
            {'exam_locator': 'p1', 'question_number': str(i), 'source': 'answers.txt', 'locator': 'p1', 'quote': line}
            for i, line in enumerate(answers.read_text(encoding='utf-8').splitlines(), 1)]})
        return root, exam, manifest, root / 'dataset.json'

    def graphs(self, root):
        index = read_json(root / 'question_graphs/index.json')
        return index, [read_json(root / 'question_graphs' / e['file']) for e in index['questions']]

    def test_multiple_isolated_graphs_shared_concepts_and_branching(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, _, state = self.setup_files(folder)
            material = root / 'material.txt'
            material.write_text('산소는 최종 전자 수용체이다.', encoding='utf-8')
            provider = QuestionFixture()
            ingest(state, material, 'learning_material', provider=provider)
            material_before = (root / 'material_graph.json').read_bytes()
            data = ingest(state, exam, 'exam', 'e', provider)
            index, graphs = self.graphs(root)
            self.assertEqual(len(graphs), 2)
            self.assertEqual(index['needs_reanalysis'], [])
            common = [{n['details']['concept_id'] for n in g['nodes'] if n['kind'] == 'concept'} for g in graphs]
            self.assertEqual(common[0], common[1])
            for graph in graphs:
                validate_question_graph(graph, data)
                self.assertEqual({n['kind'] for n in graph['nodes']},
                                 {'concept', 'task', 'reasoning', 'evidence_of_understanding', 'assessment_intent'})
                self.assertEqual(graph['actual_student_behavior'], 'not_observed')
                self.assertEqual(graph['answer_key_context']['status'], 'not_provided')
                self.assertEqual(next(n for n in graph['nodes'] if n['kind'] == 'assessment_intent')['details']['status'], 'hypothesis')
                self.assertTrue(all(ref['question_id'] == graph['question_id'] for n in graph['nodes'] for ref in n['evidence']))
                self.assertTrue(all(n['details']['criteria_status'] == 'candidate' for n in graph['nodes'] if n['kind'] == 'evidence_of_understanding'))
            first = next(g for g in graphs if g['question_number'] == '1')
            reason_links = [e for e in first['edges'] if e['from'] == 'reasoning:s0' and e['to'].startswith('reasoning:')]
            self.assertEqual({e['to'] for e in reason_links}, {'reasoning:s1', 'reasoning:s2'})
            self.assertEqual((root / 'material_graph.json').read_bytes(), material_before)
            before = {p.name: p.read_bytes() for p in (root / 'question_graphs').glob('*.json')}
            calls = provider.calls
            ingest(state, exam, 'exam', 'e', provider)
            self.assertEqual(provider.calls, calls)
            self.assertEqual(before, {p.name: p.read_bytes() for p in (root / 'question_graphs').glob('*.json')})

    def test_answer_keys_are_question_scoped_and_retained_in_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, manifest, state = self.setup_files(folder)
            provider = QuestionFixture()
            data = ingest(state, exam, 'exam', 'e', provider, answer_key=manifest)
            self.assertEqual(len(provider.inputs), 2)
            for inputs in provider.inputs:
                number = inputs['question'].split('.', 1)[0]
                self.assertEqual(len(inputs['answer_key_blocks']), 1)
                self.assertTrue(inputs['answer_key_blocks'][0]['text'].startswith(number + '.'))
            self.assertEqual({s['kind'] for s in data['sources']}, {'exam', 'answer_key'})
            _, graphs = self.graphs(root)
            for graph in graphs:
                self.assertEqual(graph['answer_key_context']['status'], 'provided')
                self.assertTrue(any(e['source_kind'] == 'answer_key' for c in graph['claims'] for e in c['evidence']))
                self.assertTrue(all(n['details']['basis'] == 'answer_key_cited' for n in graph['nodes'] if n['kind'] == 'evidence_of_understanding'))
                validate_question_graph(graph, data)
            # Whole-document access does not permit references to another question's key block.
            corrupted = copy.deepcopy(data)
            q1, q2 = corrupted['questions']
            q1['claims'][0]['evidence'] = [{'source_id': q2['answer_key_context']['blocks'][0]['source_id'],
                 'locator': 'p1', 'quote': q2['answer_key_context']['blocks'][0]['text']}]
            with self.assertRaisesRegex(ValueError, 'outside'):
                validate(corrupted)
            corrupted = copy.deepcopy(data)
            corrupted['questions'][0]['answer_key_context']['blocks'] = corrupted['questions'][1]['answer_key_context']['blocks']
            with self.assertRaisesRegex(ValueError, 'different question'):
                validate(corrupted)

    def test_partial_key_mapping_does_not_supply_the_other_question(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, manifest, state = self.setup_files(folder)
            value = read_json(manifest)
            value['entries'] = value['entries'][:1]
            save(manifest, value)
            data = ingest(state, exam, 'exam', 'e', QuestionFixture(), answer_key=manifest)
            self.assertEqual([q['answer_key_context']['status'] for q in data['questions']], ['provided', 'not_provided'])

    def test_invalid_key_mapping_preserves_existing_state_and_graphs(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, manifest, state = self.setup_files(folder)
            ingest(state, exam, 'exam', 'e', QuestionFixture())
            before = state.read_bytes()
            graph_before = (root / 'question_graphs/index.json').read_bytes()
            original = read_json(manifest)
            for field, value in [('exam_id', 'wrong'), ('quote', '없는 인용'), ('question_number', '999')]:
                altered = copy.deepcopy(original)
                if field == 'exam_id':
                    altered[field] = value
                else:
                    altered['entries'][0][field] = value
                save(manifest, altered)
                with self.assertRaises(ValueError):
                    ingest(state, exam, 'exam', 'e', QuestionFixture(), answer_key=manifest, refresh=True)
                self.assertEqual(state.read_bytes(), before)
                self.assertEqual((root / 'question_graphs/index.json').read_bytes(), graph_before)

    def test_changed_answer_keys_require_refresh_and_graph_revision_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, manifest, state = self.setup_files(folder)
            ingest(state, exam, 'exam', 'e', QuestionFixture())
            before = state.read_bytes()
            with self.assertRaisesRegex(ValueError, 'refresh'):
                ingest(state, exam, 'exam', 'e', QuestionFixture(), answer_key=manifest)
            self.assertEqual(state.read_bytes(), before)
            data = ingest(state, exam, 'exam', 'e', QuestionFixture(), answer_key=manifest, refresh=True)
            _, graphs = self.graphs(root)
            self.assertTrue(all(g['revision'] == 2 for g in graphs))
            self.assertEqual(len(list((root / 'question_graphs/history').glob('*.json'))), 2)
            # Refresh without a replacement manifest retains its explicit mapping.
            data = ingest(state, exam, 'exam', 'e', QuestionFixture(), refresh=True)
            self.assertTrue(all(q['answer_key_context']['status'] == 'provided' for q in data['questions']))

    def test_graph_tampering_and_key_span_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, manifest, state = self.setup_files(folder)
            data = ingest(state, exam, 'exam', 'e', QuestionFixture(), answer_key=manifest)
            _, graphs = self.graphs(root)
            graph = copy.deepcopy(graphs[0])
            node = next(n for n in graph['nodes'] if n['kind'] == 'evidence_of_understanding')
            node['details']['success_criteria'] = ['바꾼 기준']
            with self.assertRaises(ValueError):
                validate_question_graph(graph, data)
            graph = copy.deepcopy(graphs[0])
            graph['actual_student_behavior'] = 'understood'
            with self.assertRaises(ValidationError):
                validate_question_graph(graph, data)
            corrupted = copy.deepcopy(data)
            corrupted['questions'][0]['answer_key_context']['blocks'][0]['text'] = '조작된 해설'
            with self.assertRaisesRegex(ValueError, 'original substring'):
                validate(corrupted)

    def test_numbered_question_omission_and_bad_task_never_commit(self):
        class Missing(QuestionFixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'questions' in value:
                    value['questions'] = value['questions'][:1]
                return value
        class BadTask(QuestionFixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'task' in value:
                    value['task']['quote'] = '다른 문항의 요구'
                return value
        class Combined(QuestionFixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'questions' in value:
                    value['questions'] = [{'number': '1', 'text': EXAM, 'context': '', 'complete': True}]
                return value
        class WrongNumber(QuestionFixture):
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'questions' in value:
                    value['questions'][0]['number'] = '99'
                return value
        for provider in (Missing(), BadTask(), Combined(), WrongNumber()):
            with tempfile.TemporaryDirectory() as folder:
                root, exam, _, state = self.setup_files(folder)
                with self.assertRaises(ValueError):
                    ingest(state, exam, 'exam', 'e', provider)
                self.assertFalse(state.exists())
                self.assertFalse((root / 'question_graphs/index.json').exists())

    def test_answer_file_changes_are_detected_without_a_manifest_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, manifest, state = self.setup_files(folder)
            ingest(state, exam, 'exam', 'e', QuestionFixture(), answer_key=manifest)
            before = state.read_bytes()
            with (root / 'answers.txt').open('a', encoding='utf-8') as f:
                f.write('\n추가 원문 설명.')
            with self.assertRaisesRegex(ValueError, 'refresh'):
                ingest(state, exam, 'exam', 'e', QuestionFixture(), answer_key=manifest)
            self.assertEqual(state.read_bytes(), before)

    def test_rejected_task_review_preserves_previous_question_graphs(self):
        class RejectTask(QuestionFixture):
            model = 'reject-task-fixture'
            def complete(self, prompt, schema):
                value = super().complete(prompt, schema)
                if 'task_verdicts' in value:
                    value['task_verdicts'][0]['status'] = 'contradicted'
                return value
        with tempfile.TemporaryDirectory() as folder:
            root, exam, _, state = self.setup_files(folder)
            ingest(state, exam, 'exam', 'e', QuestionFixture())
            before = state.read_bytes()
            index_before = (root / 'question_graphs/index.json').read_bytes()
            with self.assertRaisesRegex(ValueError, '의미 검토'):
                ingest(state, exam, 'exam', 'e', RejectTask(), refresh=True)
            self.assertEqual(state.read_bytes(), before)
            self.assertEqual((root / 'question_graphs/index.json').read_bytes(), index_before)

    def test_legacy_requires_reanalysis_and_retired_graphs_are_archived(self):
        with tempfile.TemporaryDirectory() as folder:
            root, exam, _, state = self.setup_files(folder)
            data = ingest(state, exam, 'exam', 'e', QuestionFixture())
            data['questions'] = data['questions'][:1]
            index = export_question_graphs(data, root / 'question_graphs')
            self.assertEqual(len(index['questions']), 1)
            self.assertEqual(len(list((root / 'question_graphs').glob('q_*.json'))), 1)
            self.assertEqual(len(list((root / 'question_graphs/history').glob('retired-*.json'))), 1)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sample = Path(__file__).resolve().parents[1] / 'data/sample.json'
            data = ingest(root / 'dataset.json', sample, 'exam')
            index = read_json(root / 'question_graphs/index.json')
            self.assertEqual(len(index['needs_reanalysis']), 6)
            self.assertEqual(index['questions'], [])
