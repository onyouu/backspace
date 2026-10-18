"""Archive an uploaded, not-yet-projected source without deleting its original."""
import argparse
import copy
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from backspace_mvp.model import read_json
from backspace_mvp.pipeline import save
from backspace_mvp.teacher_update import TeacherModelUpdateEngine
from backspace_mvp.understanding import review_saved_note


def exclude_file(storage, file_id):
    storage = Path(storage).resolve()
    workspace = storage / 'workspace'
    files_path = workspace / 'files.json'
    files = read_json(files_path)
    row = next(r for r in files if r['id'] == file_id)
    if any(read_json(p)['status'] in ('queued', 'running') for p in (storage / 'jobs').glob('*.json')):
        raise ValueError('현재 작업이 끝난 뒤 제외하세요.')
    root = workspace / row['target']
    source_id = row.get('pipeline_source_id', file_id)
    dataset_path = root / 'dataset.json'
    if dataset_path.exists() and any(s['id'] == source_id for s in read_json(dataset_path)['sources']):
        raise ValueError('이미 지도에 반영된 자료는 그래프까지 함께 갱신해야 합니다.')
    original = workspace / 'uploads' / (file_id + row['suffix'])
    if hashlib.sha256(original.read_bytes()).hexdigest() != row['sha256']:
        raise ValueError('원본 해시가 다릅니다.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    archive = workspace / 'excluded' / (file_id + '-' + stamp)
    paths = [root / 'memory/source_manifests' / (source_id + '.json')]
    paths += [p for p in (root / 'pipeline_state/tasks').glob('*.json')
              if read_json(p)['source_id'] in (source_id, file_id)]
    for path in [original, archive, *paths]:
        if not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError('작업공간 밖의 경로입니다.')
    manifest_path = paths[0]
    manifest = read_json(manifest_path) if manifest_path.exists() else None
    state_path = root / 'teacher_model/state.json'
    engine = None
    if state_path.exists():
        engine = TeacherModelUpdateEngine(state_path.parent, scope=read_json(state_path)['scope'])
    archive.mkdir(parents=True)
    shutil.copy2(files_path, archive / 'files_before.json')
    shutil.copy2(original, archive / original.name)
    if engine:
        shutil.copy2(state_path, archive / 'teacher_state_before.json')
        current = {eid: copy.deepcopy(e['record']) for eid, e in engine.state['evidence'].items()
                   if e['current'] and not any(c['source'] == source_id for c in e['record']['citations'])}
        engine.reconcile_evidence(current)
    for nid in manifest['note_ids'] if manifest else []:
        review_saved_note(root / 'memory', nid, 'rejected', '사용자 요청으로 자료를 분석 대상에서 제외함')
    for path in paths:
        if path.exists():
            target = archive / path.relative_to(workspace)
            target.parent.mkdir(parents=True, exist_ok=True)
            path.rename(target)
    topics_path = root / 'memory/topics.json'
    if topics_path.exists():
        topics = read_json(topics_path)
        removed = set(manifest['note_ids'] if manifest else [])
        topics['topics'] = {key: [nid for nid in ids if nid not in removed]
                            for key, ids in topics['topics'].items() if any(nid not in removed for nid in ids)}
        topics['active_notes'] = sum(len(read_json(p)['note_ids'])
            for p in (root / 'memory/source_manifests').glob('*.json'))
        save(topics_path, topics)
    save(files_path, [r for r in files if r['id'] != file_id])
    save(archive / 'exclusion.json', {'file': row, 'source_id': source_id,
         'reason': '사용자 요청', 'original_preserved': str(original), 'at': stamp})
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', default='state/web')
    parser.add_argument('--file-id', required=True)
    args = parser.parse_args()
    print(exclude_file(args.storage, args.file_id))
