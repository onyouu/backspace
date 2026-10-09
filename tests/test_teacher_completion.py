"""A Jev abstention is a review result, not an endless generation retry."""
import unittest

from backspace_mvp.teacher_reliability import CLOSED, result_summary


class TeacherCompletionTests(unittest.TestCase):
    def test_uncertain_judgement_is_explicit_insufficient_evidence(self):
        result = result_summary({'e1': {}}, [], {'bundle': {'status': 'pending_review'}}, {})
        self.assertEqual(result['kind'], 'insufficient_evidence')
        self.assertEqual(result['pending_clusters'], 1)
        self.assertIn('pending_review', CLOSED)

    def test_transport_failure_remains_retryable(self):
        result = result_summary({'e1': {}}, [], {'bundle': {'status': 'failed_retryable'}}, {})
        self.assertEqual(result['kind'], 'generation_pending')


if __name__ == '__main__':
    unittest.main()
