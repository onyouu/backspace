import copy
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace

from backspace_mvp.model_exports import portable_model, archive_export
from backspace_mvp.pipeline import digest
from backspace_mvp.prompt_context import pack_context, material_context
from backspace_mvp.web import make_server


def fixture():
    ref = {'source': 's1', 'locator': 'p1', 'raw_evidence': 'Only when X is present, Y is inhibited.',
           'char_start': 10, 'char_end': 49}
    relation = {'id': 'r1', 'from': 'a', 'to': 'b', 'relation': 'inhibits',
                'statement': 'X inhibits Y', 'conditions': ['X present'], 'evidence': [ref]}
    m = {'content_hash': 'original-model', 'revision': 2, 'scope': {}, 'status': 'needs_review',
         'material_sources': [{'id': 's1', 'title': 'Lesson', 'sha256': 'original-sha',
             'path': 'private-path', 'perception': {'blocks': [{'bbox': [0, 0, 4, 4]}]}}],
         'concept_importance': [{'concept_id': x, 'label': x, 'aliases': [], 'teacher_importance': None} for x in ['a', 'b']],
         'material_relations': [relation],
         'evidence_registry': [{'id': 'e1', 'kind': 'teaching_observation', 'citations': [ref]}],
         'assessment_ideals': [{'id': 'h1', 'statement': 'Conditional prediction', 'status': 'provisional',
             'readiness': 'needs_review', 'reasoning_chain': ['X then Y'], 'applicable_context': {'conditions': ['X present']},
             'supporting_evidence': [{'evidence_id': 'e1'}], 'counter_evidence': [{'evidence_id': 'e1'}],
             'alternative_explanations': ['topic-specific'], 'limitations': ['one lesson']} ]}
    g = {'concepts': [{'id': 'a', 'evidence': [ref]}],
         'relations': [{'id': 'edge1', 'from': 'a', 'to': 'b', 'relation': 'inhibits', 'assertions': [relation]}]}
    return m, g, ref


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model, self.graph, self.ref = fixture()
        for name, value in [('teacher/teacher_model.json', self.model), ('teacher/material_graph.json', self.graph),
                            ('perception/source/document.json', {'original': 'unchanged'}), ('files.json', [])]:
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding='utf8')
        (self.root / 'uploads').mkdir(); (self.root / 'uploads/source.pdf').write_bytes(b'%PDF-test-original')

    def test_runtime_keeps_all_conditions_and_resolvable_witnesses_without_mutation(self):
        before = copy.deepcopy((self.model, self.graph))
        runtime, evidence = portable_model(self.model, self.graph)
        self.assertEqual(before, (self.model, self.graph))
        self.assertNotIn('bbox', json.dumps(runtime)); self.assertNotIn('private-path', json.dumps(evidence))
        self.assertEqual(runtime['evidence_hash'], digest(evidence))
        self.assertEqual(len(evidence['citations']), 1)
        cid = runtime['assertions'][0]['citation_ids'][0]
        self.assertEqual(evidence['citations'][cid]['quote'], self.ref['raw_evidence'])
        self.assertEqual(runtime['hypotheses'][0]['applicable_context']['conditions'], ['X present'])
        self.assertEqual(runtime['hypotheses'][0]['counter_evidence_ids'], ['e1'])
        self.assertEqual(runtime['hypotheses'][0]['readiness'], 'needs_review')
        self.assertEqual(runtime['relations'][0]['assertion_ids'], ['r1'])

    def test_archives_preserve_bytes_and_manifest_excludes_credentials(self):
        (self.root / '.env').write_text('secret')
        (self.root / 'teacher/auth.json').write_text('secret')
        for kind in ('backup', 'recognition'):
            with archive_export(self.root, kind) as f, zipfile.ZipFile(f) as z:
                names = z.namelist()
                self.assertFalse(any('.env' in n or 'auth.json' in n for n in names))
                manifest = json.loads(z.read('manifest.json'))
                for entry in manifest['files']:
                    body = z.read(entry['path'])
                    self.assertEqual(hashlib.sha256(body).hexdigest(), entry['sha256'])
                    if entry['path'].startswith('workspace/'):
                        self.assertEqual(body, (self.root / entry['path'][10:]).read_bytes())
                self.assertEqual('workspace/uploads/source.pdf' in names, kind == 'backup')
                self.assertEqual('model-recognition.json' in names, kind == 'recognition')

    def test_http_downloads_and_busy_guard(self):
        def base(mode):
            if mode != 'workspace': raise ValueError('Unknown mode')
            return self.root
        store = SimpleNamespace(mutex=threading.RLock(), active=None, base=base, clean=lambda x: x)
        server = make_server(0, store)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:' + str(server.server_port)
        for kind in ('model', 'evidence', 'recognition', 'backup'):
            with urllib.request.urlopen(url + '/api/export?mode=workspace&kind=' + kind) as response:
                self.assertIn('attachment;', response.headers['Content-Disposition'])
                body = response.read()
                self.assertEqual(len(body), int(response.headers['Content-Length']))
                self.assertTrue(body.startswith(b'PK') if kind in ('backup', 'recognition') else json.loads(body))
        for query in ('kind=../.env', 'mode=../workspace&kind=model'):
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(url + '/api/export?' + query)
        store.active = 'running'
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(url + '/api/export?mode=workspace&kind=model')


class PromptTests(unittest.TestCase):
    def test_exact_concept_identity_wins_over_ambiguous_aliases(self):
        from backspace_mvp.study_plan import _teacher_context, _compact_teacher_context
        model, _, _ = fixture()
        for c in model['concept_importance']:
            c.update(label='same', aliases=[], status='not_scored')
        model['assessment_ideals'] = []
        node = {'id': 'a', 'label': 'same', 'aliases': []}
        context = _teacher_context(model, node, [], {})
        self.assertEqual(context['matched_concept_ids'], ['a'])
        self.assertEqual(_compact_teacher_context(context, model)['comparison_concepts'][0]['observed_question_count'], 0)
        with self.assertRaises(ValueError):
            _teacher_context(model, {**node, 'id': 'unknown'}, [], {})

    def test_quotes_deduplicate_but_offsets_conditions_and_counterevidence_survive(self):
        _, _, ref = fixture()
        context = {'conditions': ['X present'], 'supporting_evidence': [ref], 'counter_evidence': [ref],
                   'limitations': ['one lesson']}
        packet = {'priorities': [{'teacher_context': context, 'evidence': [ref]} for _ in range(10)]}
        before = copy.deepcopy(packet)
        packed = pack_context(packet)
        self.assertEqual(packet, before)
        self.assertEqual(len(packed['citation_table']), 1)
        self.assertEqual(len(packed['teacher_context_table']), 1)
        self.assertLess(len(json.dumps(packed)), len(json.dumps(packet)))
        c = next(iter(packed['teacher_context_table'].values()))
        self.assertEqual(c['conditions'], ['X present']); self.assertTrue(c['counter_evidence'])
        quote = next(iter(packed['citation_table'].values()))
        self.assertEqual(quote['quote'], ref['raw_evidence']); self.assertEqual(quote['start'], 10)
        shifted = {**ref, 'char_start': 100, 'char_end': 139}
        self.assertEqual(len(pack_context({'refs': [ref, shifted]})['citation_table']), 2)

    def test_material_selection_excludes_ocr_and_reports_omissions(self):
        m, _, ref = fixture()
        node = {'id': 'a', 'label': 'A', 'perception': {'bbox': [0, 0]}, 'evidence': [ref]}
        value = material_context(node, m['material_relations'] * 15)
        self.assertNotIn('perception', value['material_node'])
        self.assertEqual(value['omitted_relation_count'], 11)
        self.assertEqual(value['material_relations'][0]['conditions'], ['X present'])


if __name__ == '__main__':
    unittest.main()
