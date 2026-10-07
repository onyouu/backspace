import hashlib
import tempfile
import unittest
from pathlib import Path

from backspace_mvp.model import read_json
from backspace_mvp.pipeline import digest, empty_dataset, save
from backspace_mvp.stage_state import StageLedger
from backspace_mvp.teacher_update import TeacherModelUpdateEngine
from backspace_mvp.understanding import list_saved_notes
from scripts.exclude_unprojected_file import exclude_file


class FileExclusionTests(unittest.TestCase):
    def test_excluded_source_keeps_original_but_leaves_active_memory_and_teacher_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp)
            workspace = storage / 'workspace'
            root = workspace / 'teacher'
            fid, sid, nid = 'test_file', 'src_test', 'un_' + 'a' * 28
            original = workspace / 'uploads' / (fid + '.pdf')
            original.parent.mkdir(parents=True)
            original.write_bytes(b'original')
            row = {'id': fid, 'target': 'teacher', 'suffix': '.pdf', 'pipeline_source_id': sid,
                   'sha256': hashlib.sha256(b'original').hexdigest()}
            save(workspace / 'files.json', [row, {**row, 'id': 'other'}])
            data = empty_dataset()
            save(root / 'dataset.json', data)
            body = 'saved interpretation'
            save(root / 'memory/notes' / (nid + '.json'), {'content_hash': digest(body)})
            (root / 'memory/notes' / (nid + '.md')).write_text(body, encoding='utf-8')
            save(root / 'memory/source_manifests' / (sid + '.json'), {'note_ids': [nid]})
            save(root / 'memory/topics.json', {'topics': {'topic': [nid]}, 'active_notes': 1})
            ledger = StageLedger(root / 'pipeline_state')
            ledger.ensure('GRAPH_PROJECTION', sid, 'hash')
            ledger.ensure('GRAPH_PROJECTION', 'src_other', 'hash')
            engine = TeacherModelUpdateEngine(root / 'teacher_model', scope=data['scope'])
            for key, source in [('excluded', sid), ('other', 'src_other')]:
                engine.register_evidence({'id': key, 'citations': [{'source': source}]})
            archive = exclude_file(storage, fid)
            self.assertEqual(original.read_bytes(), b'original')
            self.assertEqual((archive / original.name).read_bytes(), b'original')
            self.assertEqual([r['id'] for r in read_json(workspace / 'files.json')], ['other'])
            self.assertEqual(list_saved_notes(root / 'memory')['active_count'], 0)
            self.assertEqual((root / 'memory/notes' / (nid + '.md')).read_text(), body)
            state = TeacherModelUpdateEngine(root / 'teacher_model', scope=data['scope']).state
            self.assertFalse(state['evidence']['excluded']['current'])
            self.assertTrue(state['evidence']['other']['current'])
            self.assertEqual([r['source_id'] for r in ledger.rows()], ['src_other'])
            self.assertEqual(read_json(root / 'memory/topics.json')['active_notes'], 0)

    def test_running_job_blocks_exclusion_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp)
            save(storage / 'workspace/files.json', [{'id': 'test'}])
            save(storage / 'jobs/running.json', {'status': 'running'})
            with self.assertRaisesRegex(ValueError, '현재 작업'):
                exclude_file(storage, 'test')
            self.assertEqual(read_json(storage / 'workspace/files.json'), [{'id': 'test'}])
            self.assertFalse((storage / 'workspace/excluded').exists())
