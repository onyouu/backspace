"""Whitespace citation recovery without network calls or original text edits."""
import copy
import tempfile
import unittest
from pathlib import Path

from backspace_mvp.grounded import exact_whitespace_span, reconcile_material
from backspace_mvp.model import validate
from backspace_mvp.pipeline import ingest


def concept(label, quote=None):
    return {'label':label, 'surface_form':label, 'quote':quote or label,
            'confidence':.9, 'explicit_emphasis':[]}


class QuoteAlignmentTests(unittest.TestCase):
    def test_only_unique_whitespace_differences_are_recovered(self):
        self.assertEqual(exact_whitespace_span('TCA\n\n회로', 'TCA 회로'), 'TCA\n\n회로')
        self.assertEqual(exact_whitespace_span('작은\n\n창자', '작은창자'), '작은\n\n창자')
        for text, quote in [('TCA\n\n회로', 'tca 회로'), ('TCA\n\n회로', 'TCA-회로'),
                            ('TCA\n\n회로', 'TCA 회로이다'), ('소화', '소 '),
                            ('TCA\n\n회로 TCA\n회로', 'TCA 회로'),
                            ('TCA' + '\n'*9 + '회로', 'TCA 회로'), ('TCA', '   ')]:
            with self.subTest(text=text, quote=quote):
                self.assertIsNone(exact_whitespace_span(text, quote))

    def test_all_concepts_and_relations_restore_verbatim_and_log_changes(self):
        text = '작은\n\n창자\n\nTCA\n\n회로\n\nTCA\n\n회로는 중요하다'
        page = {'text':text}
        value = {'concepts':[concept('작은창자'), concept('TCA 회로', 'TCA 회로는 중요하다')],
                 'relations':[{'from_label':'작은창자', 'to_label':'TCA 회로',
                               'quote':'TCA 회로는 중요하다', 'confidence':.9}]}
        value['concepts'][1]['explicit_emphasis'] = ['TCA 회로는 중요하다']
        changes = reconcile_material(value, page, [])
        self.assertEqual(value['concepts'][0]['surface_form'], '작은\n\n창자')
        self.assertEqual(value['concepts'][1]['surface_form'], 'TCA\n\n회로')
        self.assertEqual(value['concepts'][1]['label'], 'TCA 회로')
        self.assertEqual(value['relations'][0]['from_label'], '작은\n\n창자')
        self.assertTrue(all(c['quote'] in text for c in value['concepts']))
        self.assertIn(value['relations'][0]['quote'], text)
        self.assertTrue(any(c.get('before') == '작은창자' for c in changes))
        self.assertEqual(page['text'], text)
        self.assertEqual(reconcile_material(value, page, []), [])

    def test_absent_or_ambiguous_quotes_are_left_for_validation(self):
        for quote in ['미토콘드리아', 'TCA 회로']:
            value = {'concepts':[concept(quote)], 'relations':[]}
            before = copy.deepcopy(value)
            self.assertEqual(reconcile_material(value, {'text':'TCA\n회로 TCA\n\n회로'}, []), [])
            self.assertEqual(value, before)

    def test_ingestion_keeps_exact_citations_and_reuses_checkpoint(self):
        class Provider:
            calls = 0
            def complete(self, prompt, schema):
                self.calls += 1
                return {'concepts':[concept('작은창자'), concept('TCA 회로')], 'relations':[]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / 'lesson.txt'
            text = '작은\n\n창자\n\nTCA\n\n회로'
            original.write_text(text, encoding='utf-8')
            provider = Provider()
            data = ingest(root / 'dataset.json', original, 'learning_material', provider=provider)
            validate(data)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(original.read_text(encoding='utf-8'), text)
            for observation in data['material_observations']:
                self.assertIn(observation['surface_form'], observation['evidence'][0]['quote'])
                self.assertIn(observation['evidence'][0]['quote'], text)
            ingest(root / 'dataset.json', original, 'learning_material', provider=provider)
            self.assertEqual(provider.calls, 1)


if __name__ == '__main__':
    unittest.main()
