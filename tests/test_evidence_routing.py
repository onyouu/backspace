"""Source-support decisions must not spend a second NVIDIA generation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from backspace_mvp.nvidia import NvidiaProvider
from backspace_mvp.semantic_control import SemanticControl
from backspace_mvp.staged import StagedExtractor
from backspace_mvp.contracts import MATERIAL_REVIEW
from backspace_mvp.pipeline import empty_dataset


class EvidenceJev:
    model = 'jev-fixture'
    def __init__(self): self.calls = 0; self.confidence = .95; self.fail = False
    def decide(self, state, questions, **kwargs):
        self.calls += 1
        if self.fail: raise ConnectionError('network_error')
        return {'model': self.model, 'answers': {key: {
            'type': 'choice', 'choice': 'supported', 'confidence': self.confidence,
            'probabilities': {k: float(k == 'supported') for k in contract['criteria']}}
            for key, contract in questions.items()}}


class EvidenceRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.nvidia = NvidiaProvider.__new__(NvidiaProvider)
        self.nvidia.complete = Mock(side_effect=AssertionError('No NVIDIA evidence decision'))
        self.ex = StagedExtractor(self.nvidia, empty_dataset(), {'id': 'source'}, root)
        self.jev = EvidenceJev()
        self.ex._evidence_control = SemanticControl(root / 'jev', provider=self.jev)
    def run_review(self):
        return self.ex.evidence_review_call('claim_grounding', 'fixture prompt', MATERIAL_REVIEW, 1536,
            lambda r: self.assertEqual(len(r['verdicts']), 1),
            evidence=[{'statement': 'ATP 감소', 'cited_texts': ['ATP 감소'], 'conditions': []}])
    def test_decision_and_replay_use_jev_cache_without_nvidia(self):
        self.assertEqual(self.run_review()['verdicts'][0]['status'], 'supported')
        self.run_review()
        self.assertEqual(self.jev.calls, 1)
        self.nvidia.complete.assert_not_called()
        self.assertTrue(self.ex.manifest['stages'][-1]['cached'])
    def test_low_confidence_cannot_promote_to_supported(self):
        self.jev.confidence = .1
        self.assertEqual(self.run_review()['verdicts'][0]['status'], 'insufficient_evidence')
        self.nvidia.complete.assert_not_called()
    def test_jev_failure_queues_instead_of_nvidia_fallback(self):
        self.jev.fail = True
        with self.assertRaises(ConnectionError): self.run_review()
        self.nvidia.complete.assert_not_called()
