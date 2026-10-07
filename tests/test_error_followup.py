"""Observed failure regressions, isolated files and no paid provider requests."""
import copy
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backspace_mvp.contracts import MATERIAL
from backspace_mvp.nvidia import (NvidiaProvider, RetryableNvidiaError,
    InvalidResponseError, SemanticReductionRequired, read_response_json,
    read_completion_stream)
from backspace_mvp.pipeline import empty_dataset, read_source, save
from backspace_mvp.stage_state import StageLedger
from backspace_mvp.staged import StagedExtractor
from backspace_mvp.web import Handler, WebStore
from test_resilience import completion


class ResponseBudgetTests(unittest.TestCase):
    def test_chunked_response_cannot_extend_deadline_by_trickling(self):
        clock = [0]
        sock = Mock()
        class SlowResponse:
            fp = SimpleNamespace(raw=SimpleNamespace(_sock=sock))
            def read1(self, size):
                clock[0] += 3
                return b' '
        with patch('backspace_mvp.nvidia.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RetryableNvidiaError, 'timeout'):
                read_response_json(SlowResponse(), 5)
        self.assertEqual([c.args[0] for c in sock.settimeout.call_args_list], [5, 2, 2])

    def test_streaming_response_obeys_total_budget(self):
        clock = [0]
        def slow_lines():
            while True:
                clock[0] += 3
                yield b': keepalive\n'
        with patch('backspace_mvp.nvidia.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RetryableNvidiaError, 'timeout'):
                read_completion_stream(slow_lines(), 5)

    def test_normal_json_and_stream_remain_supported(self):
        self.assertEqual(read_response_json(io.BytesIO(b'{"ok":true}'), 5), {'ok': True})
        raw = (b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
               b'data: [DONE]\n\n')
        self.assertEqual(read_completion_stream(io.BytesIO(raw), 5)['choices'][0]['message']['content'], 'ok')

    def test_oversized_response_is_rejected(self):
        with self.assertRaisesRegex(InvalidResponseError, 'response_too_large'):
            read_response_json(io.BytesIO(b' '*8_000_001), 5)


class EmphasisContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'NVIDIA_API_KEY':'fixture', 'NVIDIA_LOG_DIR':self.temp.name}, clear=True)
        env.start(); self.addCleanup(env.stop)
        self.provider = NvidiaProvider(env_file=Path(self.temp.name)/'missing.env', task='learning_material')
        self.concept = {'label':'TCA 회로', 'surface_form':'TCA 회로', 'quote':'중요: TCA 회로',
                        'confidence':0.8, 'explicit_emphasis':[]}

    def test_empty_and_wrapped_emphasis_are_repaired_without_another_call(self):
        for emphasis in (None, [None], [{'quote':'중요: TCA 회로'}, None]):
            with self.subTest(emphasis=emphasis):
                item = {**self.concept, 'explicit_emphasis':emphasis}
                with patch('urllib.request.urlopen', return_value=completion(content=json.dumps({'concepts':[item], 'relations':[]}))) as request:
                    result = self.provider.complete('원문', MATERIAL)
                self.assertEqual(request.call_count, 1)
                self.assertEqual(result['concepts'][0]['quote'], self.concept['quote'])
                self.assertEqual(result['concepts'][0]['explicit_emphasis'], ['중요: TCA 회로'] if isinstance(emphasis, list) and emphasis and isinstance(emphasis[0], dict) else [])
                self.assertTrue(self.provider.attempts[-1]['contract_normalizations'])

    def test_invalid_entries_and_required_fields_are_not_silently_discarded(self):
        for item in ({**self.concept, 'explicit_emphasis':[42]},
                     {**self.concept, 'explicit_emphasis':[{'statement':'중요: TCA 회로'}]},
                     {**self.concept, 'quote':None}):
            with self.subTest(item=item):
                with patch('urllib.request.urlopen', return_value=completion(content=json.dumps({'concepts':[item], 'relations':[]}))) as request:
                    with self.assertRaisesRegex(ValueError, 'schema_invalid'):
                        self.provider.complete('원문', MATERIAL)
                self.assertEqual(request.call_count, 1)

    def test_header_wait_consumes_response_budget_without_extra_request(self):
        clock = [0]; response = completion(); response.read = Mock()
        def headers(*a, **k):
            clock[0] = 46
            return response
        with patch('backspace_mvp.nvidia.time.monotonic', side_effect=lambda: clock[0]), patch('urllib.request.urlopen', side_effect=headers) as request:
            with self.assertRaisesRegex(ValueError, 'timeout'):
                self.provider.complete('원문', MATERIAL)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs['timeout'], 45)
        response.read.assert_not_called()

    def test_emphasis_repair_does_not_bypass_source_grounding(self):
        from backspace_mvp.nvidia import normalize_emphasis_contract
        raw = {'concepts':[{**self.concept, 'explicit_emphasis':[{'quote':'중요: TCA 회로'}]}], 'relations':[]}
        normalize_emphasis_contract(raw, MATERIAL)
        provider = SimpleNamespace(complete=lambda *a, **k: copy.deepcopy(raw), model='fixture')
        path = Path(self.temp.name)/'source.txt'; path.write_text('TCA 회로', encoding='utf-8')
        source = read_source(path, 'learning_material')
        # Source lacks the claimed emphasis; deterministic contract repair must not make it evidence.
        extractor = StagedExtractor(provider, empty_dataset(), source, Path(self.temp.name)/'checkpoints')
        with self.assertRaises(ValueError):
            extractor.extract()


class LeafResumeTests(unittest.TestCase):
    def test_failed_leaf_is_attempted_once_on_explicit_resume_then_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root/'source.txt'; path.write_text('ATP 생성', encoding='utf-8')
            source = read_source(path, 'learning_material'); calls = []
            class Provider:
                model = 'fixture'
                def complete(self, *args):
                    calls.append(1)
                    if len(calls) == 1:
                        raise SemanticReductionRequired('timeout', stage='material:p1', reason='timeout')
                    return {'concepts':[], 'relations':[]}
            for index in range(3):
                extractor = StagedExtractor(Provider(), empty_dataset(), source, root/'checkpoints')
                if index == 0:
                    with self.assertRaises(SemanticReductionRequired): extractor.extract()
                else: extractor.extract()
            self.assertEqual(len(calls), 2, 'Resume retries the bounded leaf; completed cache makes no call')


class BrowserDisconnectTests(unittest.TestCase):
    def test_outdated_runtime_cannot_launch_more_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            store=WebStore(storage=Path(folder))
            with patch('backspace_mvp.web.backend_revision',return_value='different-version'):
                with self.assertRaisesRegex(ValueError,'서버 업데이트'):
                    store.start('teacher',{'mode':'workspace'})
            self.assertIsNone(store.active)
            self.assertEqual(store.jobs,{})
    def test_closed_socket_does_not_attempt_another_response(self):
        for where in ('headers', 'body'):
            with self.subTest(where=where):
                handler = Handler.__new__(Handler)
                handler.send_response = Mock(); handler.send_header = Mock()
                handler.end_headers = Mock(side_effect=BrokenPipeError() if where=='headers' else None)
                handler.wfile = SimpleNamespace(write=Mock(side_effect=ConnectionAbortedError()))
                handler.close_connection = False
                handler.send(200, b'answer')
                self.assertTrue(handler.close_connection)
                self.assertEqual(handler.send_response.call_count, 1)
                self.assertEqual(handler.wfile.write.call_count, 0 if where=='headers' else 1)


class ReadOnlyOutcomeTests(unittest.TestCase):
    def test_repeated_graph_contract_error_requires_review_not_endless_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=StageLedger(Path(folder)/'pipeline_state')
            for stage in ('PERCEPTION','UNDERSTANDING'):
                ledger.set(ledger.ensure(stage,'source','hash'),'complete')
            graph=ledger.ensure('GRAPH_PROJECTION','source','hash')
            def invalid():raise ValueError('개념 quote가 원문에 없습니다.')
            ledger.run(graph,invalid)
            self.assertEqual(graph['status'],'failed_retryable')
            ledger.run(graph,invalid)
            self.assertEqual(graph['status'],'rejected')
            self.assertFalse(ledger.pending())
            summary=ledger.snapshot()
            self.assertEqual(summary['review_count'],1)
            self.assertEqual(summary['retryable_count'],0)
            self.assertEqual(summary['pending_count'],1,'Review must not be disguised as completion')
            self.assertEqual(summary['outcome'],'needs_review')

    def test_demo_views_refresh_without_changing_dataset_or_existing_plan(self):
        from backspace_mvp.model import read_json
        from backspace_mvp.materials import validate_material_graph
        with tempfile.TemporaryDirectory() as folder, patch('urllib.request.urlopen', side_effect=AssertionError('No API')):
            storage = Path(folder); store = WebStore(storage=storage)
            state = storage/'demo/scope/dataset.json'; plan = storage/'demo/current_plan.json'
            data = read_json(state); data['sources'][0]['title'] += ' · revised fixture'
            save(state, data)
            before = state.read_bytes(); plan_before = plan.read_bytes()
            with self.assertRaises(ValueError):
                validate_material_graph(read_json(state.parent/'material_graph.json'), data)
            WebStore(storage=storage)
            validate_material_graph(read_json(state.parent/'material_graph.json'), data)
            self.assertEqual(state.read_bytes(), before)
            self.assertEqual(plan.read_bytes(), plan_before)
            self.assertTrue(list((state.parent/'material_graph_history').glob('*.json')))

    def test_one_read_failure_does_not_hide_successful_other_file(self):
        with tempfile.TemporaryDirectory() as folder, patch('urllib.request.urlopen', side_effect=AssertionError('No API')):
            store = WebStore(storage=Path(folder))
            store.upload(b'ATP', 'good.txt', 'teacher', 'material')
            store.upload(b'TCA', 'bad.txt', 'teacher', 'material')
            original = store._read_file
            def read(row, progress):
                if row['name']=='bad.txt': raise ConnectionError('reader unavailable')
                return original(row, progress)
            with patch.object(store, '_read_file', side_effect=read):
                job = store.start('read', {'mode':'workspace', 'target':'teacher'})
                deadline = time.monotonic()+8
                while store.active and time.monotonic()<deadline: time.sleep(.01)
            self.assertIsNone(store.active)
            result = store.jobs[job['id']]
            self.assertEqual(result['status'], 'done')
            self.assertEqual(result['outcome'], 'partial_success')
            self.assertEqual(sum(t['status']=='complete' for t in result['stage_tasks']), 1)
            self.assertFalse((store.workspace/'teacher/memory/notes').exists())

    def test_read_ignores_old_graph_failure_and_keeps_analysis_status(self):
        with tempfile.TemporaryDirectory() as folder, patch('urllib.request.urlopen', side_effect=AssertionError('No API')):
            store = WebStore(storage=Path(folder)); row = store.upload(b'ATP', 'file.txt', 'teacher', 'material')
            files = store.files(); files[0].update(pipeline_source_id='old-source', pipeline_input_hash='old-hash', pipeline_outcome='partial_success')
            save(store.workspace/'files.json', files)
            ledger = StageLedger(store.workspace/'teacher/pipeline_state')
            task = ledger.ensure('GRAPH_PROJECTION', 'old-source', 'old-hash')
            ledger.set(task, 'failed_retryable', reason='timeout')
            job = store.start('read', {'mode':'workspace', 'target':'teacher'})
            deadline = time.monotonic()+8
            while store.active and time.monotonic()<deadline: time.sleep(.01)
            self.assertIsNone(store.active)
            result = store.jobs[job['id']]
            self.assertEqual(result['outcome'], 'complete', result)
            self.assertEqual(result['stored_notes'], 0)
            self.assertEqual({t['stage'] for t in result['stage_tasks']}, {'PERCEPTION'})
            self.assertEqual(store._file(row['id'])['pipeline_outcome'], 'partial_success')
            self.assertEqual(result['step'], '텍스트·이미지 읽기 완료')


if __name__ == '__main__': unittest.main()
