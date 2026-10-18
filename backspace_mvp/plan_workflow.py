"""Plan-only job path. Never re-extracts study sources or rebuilds the teacher."""
from .model import read_json
from .pipeline import digest
from .stage_state import StageLedger
from .study_plan import generate_study_plan, CONTEXT_VERSION


def execute_plan(store, job, options, progress):
    base = store.base(job['mode'])
    data = store.data(job['mode'])
    if not data['model'] or data['model_stale']:
        raise ValueError('최신 Teacher Model을 먼저 생성하세요.')
    parameters = {k: options.get(k, v) for k, v in (
        ('days', 7), ('daily_minutes', 60), ('exam_format', '서술형'), ('max_concepts', 4),
        ('offline', True), ('materials_origin', 'scope'), ('focus', ''))}
    origin = parameters['materials_origin']
    if origin not in ('teacher', 'scope'):
        raise ValueError('계획에 사용할 학습 범위를 확인하세요.')
    graph = data['material'] if origin == 'teacher' else data['scope_material']
    if not graph or not graph['concepts']:
        raise ValueError('선택한 범위에 분석된 학습자료가 없습니다.')
    if any(f['target'] == origin and not f.get('excluded_from_model') and
           (f.get('analysis_stale') or f['status'] == 'pending') for f in data['files']):
        raise ValueError('선택한 범위의 새 자료 분석을 먼저 마쳐 주세요.')
    old = data.get('plan')
    pending = [e for e in (old or {}).get('events', [])
               if e['type'] != 'progress' and e['id'] not in (old or {}).get('processed_event_ids', [])]
    ih = digest([CONTEXT_VERSION, data['model']['content_hash'], graph['content_hash'], parameters, pending])
    ledger = StageLedger(base / 'teacher/pipeline_state', clean=store.clean)
    task = ledger.ensure('PLANNING', '_planning', ih, checkpoint=base / 'current_plan.json', payload=parameters)
    # The planner owns idempotency. A completed ledger entry must not accidentally
    # return plan B when the user selects a previously generated plan A again.
    ok, plan = ledger.run(task, lambda: generate_study_plan(
        base / 'teacher/teacher_model.json', base / origin / 'dataset.json',
        out=base / 'current_plan.json', progress=progress, **parameters), force=True)
    if not ok:
        job.update(status='failed', outcome='plan_failed', target='teacher',
                   step='기존 계획을 보존했습니다. 설정을 확인하고 다시 생성하세요.',
                   error=task.get('last_error', {}).get('message'), stage_tasks=[store.clean(task)], pending_count=1)
        return
    # Superseded failed attempts remain in diagnostics, not as actionable retries.
    for previous in ledger.rows():
        if previous['stage'] == 'PLANNING' and previous['task_id'] != task['task_id'] and previous['status'] not in ('complete', 'skipped'):
            ledger.set(previous, 'skipped', reason='new_plan_saved')
    job.update(status='done', outcome='complete', target='teacher', step='학습계획과 일정을 저장했습니다.',
               completed_steps=['학습계획'], stage_tasks=[store.clean(task)], pending_count=0,
               plan_revision=plan['revision'], task_count=len(plan['tasks']),
               teacher_hypothesis_count=len({h for t in plan['tasks'] for h in t['teacher_hypothesis_ids']}))
