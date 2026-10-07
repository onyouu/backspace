"""Persist transport metadata only. Usage is observed, prices are not guessed."""
from datetime import datetime, timezone


def record_usage(path, run_id, attempts):
    from .model import read_json
    from .pipeline import save
    log = read_json(path) if path.exists() else {'schema_version': '1.0', 'runs': {}}
    keys = {'stage', 'model', 'status', 'elapsed_seconds', 'prompt_chars', 'schema_chars',
            'max_tokens', 'timeout_seconds', 'usage', 'finish_reason', 'reasoning_effort',
            'output_chars', 'http_status', 'validation_path', 'validation_rule','retry_index','retry_policy'}
    log['runs'][run_id] = {'provider': 'nvidia', 'role': 'evidence_extraction_and_review',
                           'attempts': [{k: v for k, v in event.items() if k in keys} for event in attempts],
                           'cost': None, 'cost_status': 'not_measured'}
    log['updated_at'] = datetime.now(timezone.utc).isoformat()
    save(path, log)
