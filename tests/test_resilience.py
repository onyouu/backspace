"""Failure-path regressions; no external requests or production state changes."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backspace_mvp.nvidia import NvidiaProvider


class Response:
    def __init__(self, raw): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.raw).encode()


def completion(reason='stop', content='{"ok":true}'):
    return Response({'choices': [{'finish_reason': reason, 'message': {'content': content}}]})


class NvidiaResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'NVIDIA_API_KEY': 'private-fixture-key',
            'NVIDIA_LOG_DIR': self.temp.name}, clear=True)
        env.start(); self.addCleanup(env.stop)
        self.provider = NvidiaProvider(env_file=Path('missing.env'), task='learning_material')
        self.schema = {'type': 'object', 'required': ['ok']}

    def test_timeout_requires_smaller_task_with_unchanged_timeout(self):
        with patch('urllib.request.urlopen', side_effect=[TimeoutError(), completion('length'),
                completion(), completion()]) as request:
            with self.assertRaisesRegex(ValueError,'timeout'):
                self.provider.complete('large page',self.schema,max_tokens=3072)
            with self.assertRaisesRegex(ValueError,'output_limit'):
                self.provider.complete('smaller page',self.schema,max_tokens=3072)
            self.assertEqual(self.provider.complete('smallest page',self.schema,max_tokens=3072),{'ok':True})
        bodies = [json.loads(c.args[0].data) for c in request.call_args_list]
        self.assertEqual([b['max_tokens'] for b in bodies], [3072]*3)
        self.assertEqual([c.kwargs['timeout'] for c in request.call_args_list], [45]*3)
        events = json.loads(self.provider.log_path.read_text())['attempts']
        self.assertEqual([e['status'] for e in events], ['timeout','output_limit','success'])
        self.assertNotIn('private-fixture-key', self.provider.log_path.read_text())

    def test_length_retry_is_bounded_and_never_accepts_truncated_json(self):
        with patch('urllib.request.urlopen', side_effect=lambda *a, **kw: completion('length')) as request:
            with self.assertRaisesRegex(ValueError, 'output_limit'):
                self.provider.complete('page', self.schema, max_tokens=3072)
        self.assertEqual(request.call_count, 1)
        self.assertEqual([json.loads(c.args[0].data)['max_tokens'] for c in request.call_args_list], [3072])
        self.assertIsNone(self.provider.last_model)

    def test_hard_token_cap_does_not_waste_another_request(self):
        with patch('urllib.request.urlopen', return_value=completion('length')) as request:
            with self.assertRaises(ValueError):
                self.provider.complete('page', self.schema, max_tokens=16000)
        self.assertEqual(request.call_count, 1)

    def test_invalid_json_is_queued_without_same_payload_model_swap(self):
        with patch('urllib.request.urlopen', side_effect=[completion(content='{bad JSON}'), completion()]) as request:
            with self.assertRaisesRegex(ValueError,'invalid_json'):
                self.provider.complete('page', self.schema, max_tokens=3072)
        self.assertEqual(request.call_count, 1)
        self.assertIn('json_error', self.provider.attempts[0])

    def test_exact_missing_endpoint_recovered_but_invented_or_substring_is_not(self):
        from backspace_mvp.grounded import reconcile_material
        value = {'concepts': [], 'relations': [dict(from_label='소화', to_label='소', confidence=.8),
            dict(from_label='없는개념', to_label='흡수', confidence=.8)]}
        changes = reconcile_material(value, {'text':'소화\n\n흡수'}, [])
        self.assertEqual({c['label'] for c in value['concepts']}, {'소화','흡수'})
        self.assertTrue(all(c['quote'] in '소화\n\n흡수' for c in value['concepts']))
        self.assertEqual(len(changes), 2)

    def test_malformed_envelopes_and_disconnects_do_not_repeat_payload(self):
        import http.client
        for bad in [Response([]), Response({'choices':None}), Response({'choices':[None]}),
                    Response({'choices':[{'finish_reason':'stop'}]}),
                    completion(content=['not text']), completion(content='```'),
                    http.client.IncompleteRead(b'partial')]:
            with self.subTest(bad=type(bad).__name__):
                self.provider.preferred_model = self.provider.model
                with patch('urllib.request.urlopen', side_effect=[bad, completion()]) as request:
                    with self.assertRaises(ValueError):self.provider.complete('page', self.schema)
                self.assertEqual(request.call_count,1)


if __name__ == '__main__': unittest.main()
