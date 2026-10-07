"""Durable stage/task ledger. Canonical notes, not downstream artifacts, are ingest commits."""
import copy
import time
import errno
from datetime import datetime, timezone
from pathlib import Path
from jsonschema import Draft202012Validator

from .model import read_json
from .pipeline import digest, save, writable

STAGES = ('PERCEPTION', 'UNDERSTANDING', 'MEMORY_PERSIST', 'MEMORY_ENRICHMENT',
          'JEV_ROUTING', 'GRAPH_PROJECTION', 'PATTERN_MINING', 'TEACHER_UPDATE',
          'TEACHER_SYNTHESIS', 'PLANNING')
STATUSES = ('not_started', 'running', 'complete', 'skipped', 'pending',
            'failed_retryable', 'failed_terminal', 'rejected')
DEPENDENCIES = {
    'PERCEPTION': (), 'UNDERSTANDING': ('PERCEPTION',),
    'MEMORY_PERSIST': ('UNDERSTANDING',), 'MEMORY_ENRICHMENT': ('MEMORY_PERSIST',),
    'JEV_ROUTING': ('MEMORY_PERSIST',), 'GRAPH_PROJECTION': ('UNDERSTANDING',),
    # Cross-source dependencies are availability checks, never an all-files barrier.
    'PATTERN_MINING': ('usable_graphs',), 'TEACHER_UPDATE': ('usable_evidence',),
    'TEACHER_SYNTHESIS': ('TEACHER_UPDATE',), 'PLANNING': ('usable_teacher_model', 'usable_scope'),
}
RETRYABLE = {'pending', 'failed_retryable', 'running'}
DONE = {'complete', 'skipped'}


def now():
    return datetime.now(timezone.utc).isoformat()


def error_type(exc):
    reason = getattr(exc, 'reason', '')
    message = str(exc).lower()
    if reason in ('timeout', 'output_limit','network_error','invalid_output','provider_error'): return reason
    if isinstance(exc, TimeoutError) or 'timeout' in message: return 'timeout'
    if isinstance(exc, (ConnectionError, OSError)) or any(s in message for s in
        ('network', 'connection_interrupted', 'decision_unavailable', 'http_5', 'http_429')):
        return 'network_error'
    if any(s in message for s in ('http 401', 'http 403', 'api_key', 'provider_error')):
        return 'provider_error'
    if 'output_limit' in message: return 'output_limit'
    return 'invalid_output'


def outcome(tasks, *, structured=False):
    """A stored subset is partial success; never claim all source units were understood."""
    tasks = list(tasks)
    understood = structured or any(t['stage'] == 'UNDERSTANDING' and t['status'] == 'complete' for t in tasks)
    if any(t['status'] == 'rejected' for t in tasks): return 'needs_review'
    unfinished = any(t['status'] not in DONE for t in tasks)
    if understood: return 'partial_success' if unfinished else 'complete'
    if any(t['status'].startswith('failed') for t in tasks): return 'failed_before_understanding'
    # Read-only and imported structured jobs do not pretend to create notes.
    return 'partial_success' if unfinished else 'complete'


class StageLedger:
    def __init__(self, folder, *, clean=lambda value: value):
        self.folder = writable(folder)
        self.clean = clean
        self.validator=Draft202012Validator(read_json(Path(__file__).parent/'schemas/stage_task.schema.json'))

    def rows(self):
        rows=[read_json(p) for p in sorted((self.folder / 'tasks').glob('*.json'))]
        for row in rows:self.validator.validate(row)
        return rows

    def ensure(self, stage, source_id, input_hash, *, note_id=None, hypothesis_id=None,
               checkpoint=None, payload=None, version_key=None):
        if stage not in STAGES: raise ValueError('Unknown pipeline stage')
        tid = digest([1, stage, source_id, note_id, hypothesis_id, input_hash, version_key])
        path = self.folder / 'tasks' / (tid + '.json')
        if path.exists():
            task = read_json(path)
            if payload is not None and task.get('payload') != payload:
                task['payload'] = payload; save(path, task)
            return task
        task = {'task_id': tid, 'stage': stage, 'source_id': source_id, 'note_id': note_id,
                'hypothesis_id': hypothesis_id, 'status': 'not_started', 'attempt_count': 0,
                'last_error': None, 'last_attempt_at': None, 'checkpoint': str(checkpoint) if checkpoint else None,
                'input_hash': input_hash, 'version_key':version_key, 'payload': payload or {}, 'created_at': now(), 'dependencies': list(DEPENDENCIES[stage])}
        save(path, task)
        if note_id and stage in ('JEV_ROUTING','MEMORY_ENRICHMENT'):
            for older in self.rows():
                if (older['task_id']!=tid and older['stage']==stage and older['source_id']==source_id
                    and older['note_id']==note_id and older['input_hash']==input_hash and older['status'] not in DONE):
                    self.set(older,'skipped',reason='task_contract_superseded',superseded_by=tid)
        return task

    def set(self, task, status, **fields):
        if status not in STATUSES: raise ValueError('Unknown stage status')
        task.update(status=status, updated_at=now(), **self.clean(fields))
        self.validator.validate(task)
        save(self.folder / 'tasks' / (task['task_id'] + '.json'), task)
        return task

    def run(self, task, fn, *, provider=None, input_size=None, force=False):
        if task['status'] in DONE and not force: return True, None
        local_dependencies=[d for d in DEPENDENCIES[task['stage']] if d in STAGES]
        if task.get('payload',{}).get('structured') and task['stage']=='GRAPH_PROJECTION':local_dependencies=[]
        if not task['source_id'].startswith('_') and local_dependencies:
            rows=self.rows()
            for dep in local_dependencies:
                if not any(r['stage']==dep and r['source_id']==task['source_id'] and
                           r['input_hash']==task['input_hash'] and r['status']=='complete' and
                           (not task['note_id'] or dep=='PERCEPTION' or r['note_id']==task['note_id']) for r in rows):
                    self.set(task,'pending',reason='dependency_unavailable:'+dep)
                    return False,None
        started = time.monotonic()
        attempt_start = len(getattr(provider, 'attempts', []))
        self.set(task, 'running', attempt_count=task['attempt_count'] + 1, last_attempt_at=now())
        try:
            result = fn()
        except Exception as exc:
            kind = error_type(exc)
            # Disk failures and provenance corruption cannot be cured by an API retry.
            terminal = isinstance(exc, (PermissionError, FileNotFoundError)) or getattr(exc,'errno',None) in (errno.ENOSPC,errno.EIO) or any(s in str(exc).lower()
                for s in ('hash mismatch', '해시가 다', '변경됐습니다', 'stale_input', 'source_changed'))
            status = 'failed_terminal' if terminal else 'failed_retryable'
            if not terminal and task['stage']=='GRAPH_PROJECTION' and kind=='invalid_output' and task['attempt_count']>=2:
                # Repeating a rejected citation/contract is not useful network recovery.
                # Preserve diagnostics and require review instead of an endless retry button.
                status='rejected'
            attempts = getattr(provider, 'attempts', [])[attempt_start:]
            details = {'stage': task['stage'], 'provider': type(provider).__name__ if provider else 'Python/local',
                       'model': getattr(provider, 'last_model', None) or getattr(provider, 'model', None),
                       'error_type': kind, 'message': self.clean(str(exc)),
                       'duration_seconds': round(time.monotonic() - started, 3),
                       'input_size': input_size, 'attempt_count': task['attempt_count'],
                       'fallback_used': len({a.get('model') for a in attempts}) > 1,
                       'checkpoint': task['checkpoint'], 'provider_attempts': copy.deepcopy(attempts)}
            log = self.folder / 'diagnostics' / (task['task_id'] + '-a' + str(task['attempt_count']) + '.json')
            save(log, self.clean(details))
            self.set(task, status, last_error=details, diagnostic=str(log))
            return False, None
        self.set(task, 'complete', last_error=None, duration_seconds=round(time.monotonic() - started, 3))
        return True, result

    def pending(self):
        return [r for r in self.rows() if r['status'] in RETRYABLE or r['status'] == 'not_started']

    def snapshot(self, *, source_ids=None, current_hashes=None):
        rows = self.rows()
        if source_ids is not None: rows = [r for r in rows if r['source_id'] in source_ids]
        if current_hashes is not None:
            rows = [r for r in rows if r['source_id'] not in current_hashes or r['input_hash'] == current_hashes[r['source_id']]]
        latest={}
        for r in sorted(rows,key=lambda t:t['created_at']):
            latest[(r['stage'],r['source_id'],r['note_id'],r['input_hash'])]=r
        rows=list(latest.values())
        counts = {s: {status: sum(r['stage'] == s and r['status'] == status for r in rows)
                      for status in STATUSES} for s in STAGES}
        return {'version': 1, 'outcome': outcome(rows), 'stages': counts, 'tasks': rows,
                'pending_count': sum(r['status'] not in DONE for r in rows),
                'retryable_count': sum(r['status'] in RETRYABLE or r['status']=='not_started' for r in rows),
                'review_count': sum(r['status'] in ('rejected','failed_terminal') for r in rows),
                'stored_notes': len({r['note_id'] for r in rows if r['stage'] == 'UNDERSTANDING' and r['status'] == 'complete' and r['note_id']})}
