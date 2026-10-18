"""Persist transport metadata only. Usage is observed, prices are not guessed."""
from datetime import datetime, timezone


def record_usage(path, run_id, attempts, *, provider='nvidia'):
    from .model import read_json
    from .pipeline import save
    log = read_json(path) if path.exists() else {'schema_version': '1.0', 'runs': {}}
    keys = {'stage', 'model', 'status', 'elapsed_seconds', 'prompt_chars', 'schema_chars',
            'max_tokens', 'timeout_seconds', 'usage', 'finish_reason', 'reasoning_effort',
            'output_chars', 'http_status', 'validation_path', 'validation_rule','retry_index','retry_policy',
            'avoided_usage','network_attempts','wait_seconds','estimated_input_tokens'}
    log['runs'][run_id] = {'provider': provider, 'role': 'evidence_extraction_and_review',
                           'attempts': [{k: v for k, v in event.items() if k in keys} for event in attempts],
                           'cost': None, 'cost_status': 'not_measured'}
    log['updated_at'] = datetime.now(timezone.utc).isoformat()
    save(path, log)


def usage_summary(path):
    from .model import read_json
    log=read_json(path) if path.exists() else {'runs':{}}
    rows=[a for run in log['runs'].values() for a in run.get('attempts',[])]
    def tokens(usage,key,alternate=None):
        value=usage.get(key)
        if value is None and alternate:value=usage.get(alternate)
        return value or 0
    def total(key,alternate=None):return sum(tokens(a.get('usage') or {},key,alternate) for a in rows)
    def combined(usage):
        value=usage.get('total_tokens')
        # Jev reports input/output separately; reasoning is already part of output.
        return value if value is not None else tokens(usage,'prompt_tokens','input_tokens')+tokens(usage,'completion_tokens','output_tokens')
    return {'requests':sum(a.get('network_attempts',0 if a.get('status')=='cache_hit' else 1) for a in rows),
        'cache_hits':sum(a.get('status')=='cache_hit' for a in rows),
        'input_tokens':total('prompt_tokens','input_tokens'),'output_tokens':total('completion_tokens','output_tokens'),
        'thought_tokens':total('thought_tokens'),'total_tokens':sum(combined(a.get('usage') or {}) for a in rows),
        'avoided_tokens':sum(combined(a.get('avoided_usage') or {}) for a in rows),
        'wait_seconds':round(sum(a.get('wait_seconds',0) for a in rows),1),
        'cost_status':'not_measured','scope':'saved_workspace_calls_only'}
