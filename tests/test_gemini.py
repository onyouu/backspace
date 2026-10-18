"""Offline contract checks for the AI Studio transport; no paid calls."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backspace_mvp.gemini import GeminiProvider
from backspace_mvp.llm_provider import create_provider, provider_class
from backspace_mvp.nvidia import ProviderStageFailure, SemanticReductionRequired


class GeminiTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = patch.dict(os.environ, {
            'GEMINI_API_KEY': 'offline-test-key',
            'GEMINI_LOG_DIR': str(self.root / 'logs'),
            'GEMINI_MODEL': 'gemini-3.6-flash',
            'BACKSPACE_FREE_LLM_ONLY': '0',
            'BACKSPACE_LLM_PROVIDER': 'gemini',
        })
        self.config.start()
        self.addCleanup(self.config.stop)

    def response(self, content, finish='STOP'):
        return io.BytesIO(json.dumps({
            'candidates': [{'content': {'parts': [{'text': content}]}, 'finishReason': finish}],
            'usageMetadata': {'promptTokenCount': 12, 'candidatesTokenCount': 8, 'totalTokenCount': 20},
        }).encode())

    def test_json_and_image_request_with_redacted_log(self):
        picture = self.root / 'page.png'
        picture.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        provider = create_provider(env_file=self.root / 'none.env', task='vision', usage_path=self.root / 'usage.json')
        self.assertIsInstance(provider, GeminiProvider)
        provider.image_inputs = [{'id': 'page-1', 'path': picture}]
        schema = {'type': 'object', 'properties': {'ok': {'const': True}}, 'required': ['ok']}
        with patch('urllib.request.urlopen', return_value=self.response('{"ok":true}')) as call:
            self.assertEqual(provider.complete('Analyze page', schema, max_tokens=256), {'ok': True})
        req = call.call_args.args[0]
        payload = json.loads(req.data)
        self.assertIn('/models/gemini-3.6-flash:generateContent', req.full_url)
        self.assertEqual(req.get_header('X-goog-api-key'), 'offline-test-key')
        self.assertEqual(payload['generationConfig']['responseMimeType'], 'application/json')
        self.assertEqual(payload['generationConfig']['responseJsonSchema']['properties']['ok']['type'], 'boolean')
        self.assertEqual(payload['generationConfig']['thinkingConfig']['thinkingLevel'], 'low')
        self.assertNotIn('temperature', payload['generationConfig'])
        self.assertTrue(payload['contents'][0]['parts'][2]['inlineData']['data'])
        logs = provider.log_path.read_text() + (self.root / 'usage.json').read_text()
        self.assertNotIn('offline-test-key', logs)
        self.assertNotIn('Analyze page', logs)
        self.assertNotIn('page-1', logs)
        self.assertNotIn('inlineData', logs)

    def test_output_limit_and_schema_failure_do_not_return_partial_result(self):
        provider = GeminiProvider(env_file=self.root / 'none.env')
        schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}
        with patch('urllib.request.urlopen', return_value=self.response('{"ok":true}', 'MAX_TOKENS')):
            with self.assertRaises(SemanticReductionRequired):
                provider.complete('x', schema)
        with patch('urllib.request.urlopen', return_value=self.response('{"ok":"yes"}')):
            with self.assertRaises(ProviderStageFailure):
                provider.complete('x', schema)
        self.assertEqual([a['status'] for a in provider.attempts], ['output_limit', 'schema_invalid'])

    def test_missing_key_and_explicit_legacy_selection(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': '', 'BACKSPACE_LLM_PROVIDER': 'gemini'}):
            with self.assertRaisesRegex(ValueError, 'GEMINI_API_KEY'):
                GeminiProvider(env_file=self.root / 'none.env')
        with patch.dict(os.environ, {'BACKSPACE_LLM_PROVIDER': 'nvidia'}):
            self.assertEqual(provider_class(self.root / 'none.env').__name__, 'NvidiaProvider')

    def test_free_api_mode_blocks_paid_routes(self):
        with patch.dict(os.environ, {'BACKSPACE_FREE_LLM_ONLY': '1', 'GEMINI_MODEL': 'gemini-4-argon'}):
            with self.assertRaisesRegex(ValueError, '무료 등급'):
                GeminiProvider(env_file=self.root / 'none.env')
        with patch.dict(os.environ, {'BACKSPACE_FREE_LLM_ONLY': '1', 'BACKSPACE_LLM_PROVIDER': 'nvidia'}):
            with self.assertRaisesRegex(ValueError, 'NVIDIA'):
                provider_class(self.root / 'none.env')


if __name__ == '__main__':
    unittest.main()
