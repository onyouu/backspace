import json
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch

from backspace_mvp.model import read_json
from backspace_mvp.pipeline import digest
from backspace_mvp.web import WebStore, make_server, MAX_FILE
from test_integration_v07 import LLMFixture, JevFixture, ROOT


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.block_network = patch('urllib.request.urlopen', side_effect=AssertionError('No API in tests'))
        self.block_network.start()
        self.addCleanup(self.block_network.stop)
        self.store = WebStore(storage=Path(self.temp.name))
        self.fixture = (ROOT / 'data/question_graph_v02/offline_fixture.json').read_bytes()

    def wait_job(self, action, **options):
        job = self.store.start(action, {'mode': 'workspace', **options})
        deadline = time.monotonic() + 15
        while self.store.jobs[job['id']]['status'] in ('queued', 'running') and time.monotonic() < deadline:
            time.sleep(.02)
        result = self.store.jobs[job['id']]
        self.assertEqual(result['status'], 'done', result.get('error'))
        return result

    def seed_teacher(self):
        self.store.upload(self.fixture, '../fixture.json', 'teacher', 'material')
        self.store.upload(self.fixture, 'fixture.json', 'teacher', 'exam', 'sample_exam')
        self.wait_job('structure')

    def test_upload_dedup_and_separate_corpora(self):
        self.seed_teacher()
        path = self.store.workspace / 'teacher/dataset.json'
        before = path.read_bytes()
        a = self.store.upload(self.fixture, 'scope.json', 'scope', 'material')
        self.assertEqual(a, self.store.upload(self.fixture, 'scope.json', 'scope', 'material'))
        self.wait_job('scope')
        self.assertEqual(before, path.read_bytes())
        scope = read_json(self.store.workspace / 'scope/dataset.json')
        self.assertFalse(scope['questions'])
        self.assertTrue(all(s['kind'] == 'learning_material' for s in scope['sources']))
        self.assertTrue(self.store.data('workspace')['scope_material']['concepts'])

    def test_raw_free_action_fails_before_any_external_request(self):
        self.store.upload(b'concept text', 'file.txt', 'teacher', 'material')
        job = self.store.start('structure', {'mode': 'workspace'})
        deadline = time.monotonic() + 5
        while self.store.active and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(self.store.jobs[job['id']]['status'], 'failed')
        self.assertFalse((self.store.workspace / 'teacher/dataset.json').exists())

    def test_read_and_review_are_independent_from_ai_and_graph_state(self):
        row=self.store.upload('ATP 생성'.encode('utf-8'),'lesson.txt','scope','material')
        self.wait_job('read',target='scope')
        self.assertFalse((self.store.workspace/'scope/dataset.json').exists())
        doc=self.store.perception(row['id'])
        block=doc['pages'][0]['blocks'][0]
        result=self.store.review({'file_id':row['id'],'revision':doc['revision'],
            'block_id':block['id'],'text':'ATP 생성과 산소'})
        self.assertEqual(result['pages'][0]['text'],'ATP 생성과 산소')
        self.assertEqual(result['pages'][0]['blocks'][0]['raw_text'],'ATP 생성')
        self.assertEqual(self.store.files()[0]['status'],'pending')
        with self.assertRaises(ValueError):self.store.perception_path('../.env')

    def test_two_inputs_teacher_and_plan_with_mocked_ai(self):
        from test_teacher_update import TeacherJev
        from backspace_mvp.semantic_control import SemanticControl
        self.seed_teacher()
        typed = TeacherJev(); typed.novel = True
        with patch('backspace_mvp.nvidia.NvidiaProvider', return_value=LLMFixture()), \
                patch('backspace_mvp.semantic_control.SemanticControl', side_effect=lambda folder, **kw: SemanticControl(folder, provider=typed)):
            self.wait_job('teacher')
        self.store.upload(self.fixture, 'scope.json', 'scope', 'material')
        self.wait_job('scope')
        self.wait_job('plan', offline=True, days=2, daily_minutes=30)
        data = self.store.data('workspace')
        plan = data['plan']
        actual_scope = read_json(self.store.workspace / 'scope/dataset.json')
        self.assertEqual(plan['inputs']['materials_dataset_hash'], digest(actual_scope))
        self.assertFalse(data['model_stale'])
        self.assertFalse(data['plan_stale'])
        self.assertTrue(plan['tasks'])
        task = plan['tasks'][0]['id']
        value = self.store.update_plan({'mode':'workspace','event_type':'progress','task_id':task,'status':'completed'})
        self.assertEqual(next(t['status'] for t in value['tasks'] if t['id']==task), 'completed')

    def test_invalid_uploads_and_options(self):
        for name,target,kind,body in [('secret.env','teacher','material',b'x'),
            ('file.pdf','scope','exam',b'x'),('empty.txt','teacher','material',b''),
            ('large.txt','teacher','material',b'x'*(MAX_FILE+1))]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.upload(body,name,target,kind)
        with self.assertRaises(ValueError):
            self.store.start('plan', {'mode':'workspace','days':True})

    def test_new_scope_and_teacher_uploads_mark_existing_results_stale(self):
        self.seed_teacher()
        with patch('backspace_mvp.nvidia.NvidiaProvider', return_value=LLMFixture()), \
                patch('backspace_mvp.scoring.JevProvider', wraps=__import__('backspace_mvp.jev', fromlist=['JevProvider']).JevProvider) as jev:
            jev.return_value = JevFixture()
            self.wait_job('teacher', manual_rebuild=True)
        self.store.upload(self.fixture, 'scope.json', 'scope', 'material')
        self.wait_job('scope')
        self.wait_job('plan', offline=True)
        before = self.store.data('workspace')
        self.assertFalse(before['plan_stale'])
        self.store.upload(b'New scope', 'scope.txt', 'scope', 'material')
        changed = self.store.data('workspace')
        self.assertTrue(changed['plan_stale'])
        self.assertFalse(changed['model_stale'])
        self.store.upload(b'New teacher source', 'teacher.txt', 'teacher', 'material')
        self.assertTrue(self.store.data('workspace')['model_stale'])

    def test_read_failure_is_visible_and_cleared_after_retry(self):
        row = self.store.upload(b'ATP', 'lesson.txt', 'teacher', 'material')
        with patch('backspace_mvp.perception.extract_document', side_effect=ValueError('damaged input')):
            with self.assertRaises(ValueError):
                self.store._read_file(row, lambda *_: None)
        self.assertEqual(self.store.files()[0]['read_error'], 'damaged input')
        self.store._read_file(self.store.files()[0], lambda *_: None)
        self.assertNotIn('read_error', self.store.files()[0])
        self.assertTrue(self.store.perception(row['id'])['complete'])

    def test_snapshot_redacts_keys_and_preserves_export_hash(self):
        self.store.secret_values.add('TEST_SECRET_abcdef')
        self.assertEqual(self.store.clean({'note':'TEST_SECRET_abcdef'}), {'note':'[REDACTED]'})
        data = self.store.data('demo')
        self.assertTrue(all('path' not in s for s in data['dataset']['sources']))
        model = data['model']
        if model:
            body = {k:v for k,v in model.items() if k not in ('content_hash','revision','updated_at','previous_hash')}
            self.assertEqual(model['content_hash'],digest(body))

    def test_visual_job_targets_one_file_without_rebuilding_model(self):
        row=self.store.upload(b'ATP','lesson.txt','scope','material')
        self.wait_job('read',target='scope')
        manifest=self.store.perception_path(row['id']); original=manifest.read_bytes()
        with patch('backspace_mvp.nvidia.NvidiaProvider') as provider, \
             patch('backspace_mvp.visual.analyze_page',return_value={'content_hash':'a'*64}) as analyze:
            result=self.wait_job('visual',file_id=row['id'],locator='p1')
        self.assertEqual(result['file_id'],row['id'])
        self.assertEqual(analyze.call_count,1)
        self.assertEqual(analyze.call_args.args[2],'p1')
        self.assertEqual(provider.call_args.kwargs['task'],'vision')
        self.assertEqual(original,manifest.read_bytes())
        self.assertFalse((self.store.workspace/'teacher/dataset.json').exists())
        self.assertFalse((self.store.workspace/'scope/dataset.json').exists())
        file=self.store.files()[0]
        self.assertEqual(file['target'],'scope')
        self.assertEqual(file['visual_pages']['p1'],'a'*64)
        self.assertEqual(file['status'],'pending')

    def test_visual_failure_keeps_existing_file_state(self):
        row=self.store.upload(b'ATP','lesson.txt','teacher','material')
        self.wait_job('read')
        before=(self.store.workspace/'files.json').read_bytes()
        with patch('backspace_mvp.nvidia.NvidiaProvider'), \
             patch('backspace_mvp.visual.analyze_page',side_effect=ValueError('incomplete_response')):
            job=self.store.start('visual',{'file_id':row['id'],'locator':'p1'})
            deadline=time.monotonic()+5
            while self.store.active and time.monotonic()<deadline:time.sleep(.02)
        self.assertEqual(self.store.jobs[job['id']]['status'],'failed')
        self.assertEqual(before,(self.store.workspace/'files.json').read_bytes())

    def test_http_static_and_same_origin_guards(self):
        self.block_network.stop() # Local HTTP only for this case; no provider actions.
        server = make_server(0, self.store)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:'+str(server.server_port)
        with urllib.request.urlopen(url+'/') as r:
            self.assertIn(b'Learning Studio',r.read())
        for path in ('/vendor/gsap.min.js','/vendor/Flip.min.js',
                     '/vendor/ScrollTrigger.min.js','/vendor/SplitText.min.js',
                     '/vendor/DrawSVGPlugin.min.js','/fonts/PretendardVariable.woff2',
                     '/fonts/SpaceGrotesk-Regular.woff2','/fonts/SpaceGrotesk-Bold.woff2',
                     '/fonts/Pretendard-LICENSE.txt','/fonts/SpaceGrotesk-LICENSE.txt',
                     '/views.js','/graph.js','/motion.js','/perception.js'):
            with self.subTest(asset=path), urllib.request.urlopen(url+path) as r:
                self.assertEqual(r.status,200)
                self.assertTrue(r.read())
        with urllib.request.urlopen(url+'/api/data?mode=demo') as r:
            self.assertEqual(json.load(r)['mode'],'demo')
        for path in ('/.env','/../.env','/vendor/../../.env','/vendor/CustomEase.min.js',
                     '/fonts/../../.env'):
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(url+path)
        request = urllib.request.Request(url+'/api/jobs', data=b'{"action":"teacher"}',
            headers={'Content-Type':'application/json','Origin':'https://evil.example','X-Backspace-Client':'web'})
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(request)
        self.assertFalse(self.store.active)


if __name__=='__main__':
    unittest.main()
