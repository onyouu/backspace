"""A provider change must not replay validated, identical page requests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backspace_mvp.gemini import GeminiProvider
from backspace_mvp.nvidia import NvidiaProvider
from backspace_mvp.pipeline import empty_dataset, save
from backspace_mvp.staged import StagedExtractor


class ProviderCheckpointReuseTests(unittest.TestCase):
    def test_exact_nvidia_request_reused_without_gemini_call(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {
            'GEMINI_API_KEY': 'test-only', 'NVIDIA_API_KEY': '',
            'NVIDIA_MATERIAL_MODEL': NvidiaProvider.LIGHTNING,
        }):
            root = Path(directory)
            env_file = root / '.env'
            env_file.write_text('', encoding='utf-8')
            gemini = GeminiProvider(env_file=env_file, task='learning_material')
            old = NvidiaProvider(env_file=env_file, task='learning_material', require_key=False)
            ex = StagedExtractor(gemini, empty_dataset(), {'id': 'source'}, root / 'checkpoints')
            schema = {'type': 'object', 'properties': {'label': {'type': 'string'}},
                      'required': ['label'], 'additionalProperties': False}
            prompt = 'source span id and source text'
            previous = ex.folder / (ex.checkpoint_identity(prompt, schema, 1400, old) + '.json')
            save(previous, {'result': {'label': 'ATP'}, 'model': old.model})
            with patch.object(gemini, 'complete', side_effect=AssertionError('paid call')):
                self.assertEqual(ex.call('span:A:p1', prompt, schema, 1400,
                                         lambda v: self.assertEqual(v['label'], 'ATP')),
                                 {'label': 'ATP'})
            self.assertTrue(ex.manifest['stages'][-1]['cached'])
            self.assertEqual(ex.manifest['stages'][-1]['model'], old.model)
            self.assertEqual(gemini.preferred_model, gemini.model)

            # A different prompt cannot borrow the earlier source's answer.
            other = ex.folder / (ex.checkpoint_identity(prompt + ' changed', schema, 1400, gemini) + '.json')
            ex.recover_nvidia_checkpoint(other, prompt + ' changed', schema, 1400,
                                         lambda v: None, gemini)
            self.assertFalse(other.exists())

    def test_invalid_old_result_cannot_cross_provider_boundary(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {
            'GEMINI_API_KEY': 'test-only', 'NVIDIA_API_KEY': '',
        }):
            root = Path(directory)
            env_file = root / '.env'
            env_file.write_text('', encoding='utf-8')
            gemini = GeminiProvider(env_file=env_file, task='learning_material')
            old = NvidiaProvider(env_file=env_file, task='learning_material', require_key=False)
            ex = StagedExtractor(gemini, empty_dataset(), {'id': 'source'}, root / 'checkpoints')
            schema = {'type': 'object', 'properties': {'label': {'type': 'string'}},
                      'required': ['label'], 'additionalProperties': False}
            previous = ex.folder / (ex.checkpoint_identity('prompt', schema, 1400, old) + '.json')
            save(previous, {'result': {'label': 'wrong quote'}, 'model': old.model})
            current = ex.folder / (ex.checkpoint_identity('prompt', schema, 1400, gemini) + '.json')
            def check(value):
                if value['label'] != 'actual source':
                    raise ValueError('not grounded')
            ex.recover_nvidia_checkpoint(current, 'prompt', schema, 1400, check, gemini)
            self.assertFalse(current.exists())
