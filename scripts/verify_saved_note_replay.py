"""Replay real committed notes in an isolated copy; forbid OCR and all network calls."""
import hashlib
import shutil
from pathlib import Path
from unittest.mock import patch
from backspace_mvp.model import read_json
from backspace_mvp.pipeline import save
from backspace_mvp.semantic_control import SemanticControl
from backspace_mvp.understanding import UnderstandingWorkspace

ROOT = Path(__file__).resolve().parents[1]


class NoGeneration:
    model = 'nvidia/nemotron-3.5-lightning-30b-a3b'
    def complete_text(self, *args, **kwargs):
        raise AssertionError('Completed understanding was called again')


class NoJev:
    model = 'jev-latest'
    def decide(self, *args, **kwargs):
        raise AssertionError('Completed Jev routing was called again')


class LocalIndex:
    def __init__(self): self.attached = set()
    def attach_committed(self, content, metadata): self.attached.add(metadata['id'])
    def close(self): pass


def verify():
    real = ROOT / 'state/web/workspace/teacher'
    report = read_json(ROOT / 'output/pipeline_recovery/real_nine_files.json')
    first = next(r for r in report['files'] if r['understanding_complete'])
    sid = first['source_id']
    destination = ROOT / 'output/pipeline_recovery/note_replay_copy'
    # No deletion: reruns overwrite only this designated verification copy.
    for child in ('notes', 'source_manifests', 'content_checkpoints'):
        shutil.copytree(real / 'memory' / child, destination / 'memory' / child, dirs_exist_ok=True)
    shutil.copytree(real / 'pipeline_state', destination / 'pipeline_state', dirs_exist_ok=True)
    source = read_json(real / 'pipeline_state/source_snapshots' / (sid + '.json'))['source']
    manifest = read_json(destination / 'memory/source_manifests' / (sid + '.json'))
    hashes = {nid: hashlib.sha256((destination / 'memory/notes' / (nid + '.md')).read_bytes()).hexdigest()
              for nid in manifest['note_ids']}
    index = LocalIndex()
    control = SemanticControl(destination / 'jev', provider=NoJev())
    with patch('urllib.request.urlopen', side_effect=AssertionError('No network in real replay')), \
         patch('backspace_mvp.perception.extract_document', side_effect=AssertionError('No OCR in real replay')):
        with UnderstandingWorkspace(destination / 'memory', provider=NoGeneration(), system=index, control=control) as workspace:
            workspace.control_version = manifest['control_version']
            attempts = {r['task_id']: r['attempt_count'] for r in workspace.ledger.rows()
                        if r['source_id'] == sid and r['stage'] in ('UNDERSTANDING', 'PERCEPTION')}
            result = workspace.ingest_source(source)
            after = {r['task_id']: r['attempt_count'] for r in workspace.ledger.rows()
                     if r['source_id'] == sid and r['stage'] in ('UNDERSTANDING', 'PERCEPTION')}
    assert attempts == after, 'Completed stage attempts changed'
    assert len(result['note_ids']) == len(manifest['note_ids']) and set(result['note_ids']) == set(manifest['note_ids']), 'Duplicate or different notes'
    assert all(hashlib.sha256((destination / 'memory/notes' / (nid + '.md')).read_bytes()).hexdigest() == sha
               for nid, sha in hashes.items()), 'Note body changed'
    value = {'source': first['name'], 'reused_notes': len(result['note_ids']), 'ocr_calls': 0,
             'understanding_calls': 0, 'jev_calls': 0, 'duplicate_notes': 0,
             'completed_stage_attempts_unchanged': True, 'note_bodies_unchanged': True,
             'local_index_fixture': True, 'original_workspace_modified': False}
    save(ROOT / 'output/pipeline_recovery/real_note_replay.json', value)
    return value


if __name__ == '__main__':
    print(verify())
