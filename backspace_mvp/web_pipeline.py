"""Resumable web orchestration around the existing extraction/teacher/plan pipeline."""
import hashlib
from pathlib import Path

from .model import read_json
from .pipeline import digest, ingest, read_source, save
from .stage_state import DONE, RETRYABLE, StageLedger, outcome

LABELS = {'PERCEPTION':'텍스트·이미지 읽기', 'UNDERSTANDING':'이해 노트 저장',
          'MEMORY_PERSIST':'기본 메모리 저장', 'MEMORY_ENRICHMENT':'메모리 검색·연결',
          'JEV_ROUTING':'Jev 판단', 'GRAPH_PROJECTION':'개념·사고 지도',
          'PATTERN_MINING':'반복 패턴', 'TEACHER_UPDATE':'교사 근거 갱신',
          'TEACHER_SYNTHESIS':'새 교사 가설', 'PLANNING':'학습계획'}


def execute(store, job, options, progress):
    if job['action'] == 'plan':
        from .plan_workflow import execute_plan
        return execute_plan(store, job, options, progress)
    if job['action'] == 'resume' and options.get('task_ids'):
        tasks = StageLedger(store.base(job['mode']) / 'teacher/pipeline_state').rows()
        selected = [t for t in tasks if t['task_id'] in options['task_ids']]
        if selected and all(t['stage'] == 'PLANNING' for t in selected):
            from .plan_workflow import execute_plan
            return execute_plan(store, job, selected[-1]['payload'], progress)
    # The study-only builder shares canonical notes, dataset and web views with
    # the legacy exam pipeline, but batches redundant generative stages.
    raw_materials=any(f['target']=='teacher' and f['kind']=='material' and f['suffix']!='.json' and not f.get('excluded_from_model') for f in store.files())
    if job['mode']=='workspace' and job['action']=='teacher' and raw_materials and options.get('strategy','efficient')=='efficient':
        from .efficient_teacher import execute as execute_efficient
        return execute_efficient(store,job,options,progress)
    if job['mode']=='workspace' and job['action']=='resume' and (store.base('workspace')/'teacher/efficient').exists() and options.get('target','teacher')=='teacher':
        from .efficient_teacher import execute as execute_efficient
        return execute_efficient(store,job,options,progress)
    from .web import KINDS
    from .understanding import UnderstandingWorkspace, source_fingerprint
    action=job['action']; resume=action=='resume'
    target=options.get('target','teacher') if action in ('read','understand','resume') else ('scope' if action=='scope' else 'teacher')
    root=store.base(job['mode'])/target
    state=root/'dataset.json'
    ledger=StageLedger(root/'pipeline_state',clean=store.clean)
    selected_tasks=set(options.get('task_ids') or [])
    initial=ledger.pending() if resume else []
    if resume and selected_tasks:
        initial=[t for t in initial if t['task_id'] in selected_tasks]
    active_hashes={r.get('pipeline_source_id',r['id']):r.get('pipeline_input_hash',r['sha256'])
                   for r in store.files() if r['target']==target}
    if resume:
        valid=[]
        for task in initial:
            if task['source_id'] in active_hashes and task['input_hash']!=active_hashes[task['source_id']]:
                ledger.set(task,'failed_terminal',reason='stale_input: source version changed')
            else:valid.append(task)
        initial=valid
    touched=set(); sources=set(); synthesized_primary_hash=None

    def run(stage,sid,ih,fn,*,provider=None,checkpoint=None,payload=None):
        teacher_stage=stage in ('TEACHER_UPDATE','TEACHER_SYNTHESIS') and sid.startswith('_')
        task=ledger.ensure(stage,sid,ih,checkpoint=checkpoint,payload=payload,
            version_key='one-run-1' if teacher_stage else None)
        touched.add(task['task_id']);sources.add(sid)
        progress(LABELS[stage])
        ok,result=ledger.run(task,fn,provider=provider,force=teacher_stage)
        if ok and LABELS[stage] not in job['completed_steps']:job['completed_steps'].append(LABELS[stage])
        return ok,result,task

    def save_row(row):
        files=store.files()
        for f in files:
            if f['id']==row['id']:f.update(row)
        save(store.workspace/'files.json',files)

    if target=='teacher' and action in ('teacher','resume') and (root/'memory/source_manifests').exists():
        from .teacher_primary import build_primary, primary_fingerprint
        # Publish available note evidence BEFORE any optional slow graph retry.
        ih=digest([digest(read_json(state)) if state.exists() else None,primary_fingerprint(root)])
        run('TEACHER_UPDATE','_teacher',ih,lambda:build_primary(state,synthesize=False),checkpoint=root/'teacher_model.json')
        ok,model,task=run('TEACHER_SYNTHESIS','_teacher',ih,lambda:build_primary(state),checkpoint=root/'teacher_model.json')
        if ok:
            synthesized_primary_hash=primary_fingerprint(root)
            if model.get('incremental',{}).get('candidate_generation_pending') or model.get('incremental',{}).get('pending_count'):
                ledger.set(task,'pending',reason='teacher_candidates_pending')

    def valid_snapshot(row):
        p=root/'pipeline_state/source_snapshots'/(row['pipeline_source_id']+'.json')
        snapshot=read_json(p);source=snapshot['source']
        original=store.workspace/'uploads'/(row['id']+row['suffix'])
        if hashlib.sha256(original.read_bytes()).hexdigest()!=source['sha256']:
            raise ValueError('source_changed: 원본이 바뀌었습니다. 새 자료 분석을 실행하세요.')
        if row.get('perception_hash')!=source.get('perception',{}).get('content_hash'):
            raise ValueError('stale_input: 원문 수정 후 이전 작업을 재개할 수 없습니다.')
        if source_fingerprint(source)!=snapshot['input_hash']:raise ValueError('hash mismatch: source snapshot')
        for loc,h in row.get('visual_pages',{}).items():
            if source.get('visual_context',{}).get(loc,{}).get('content_hash')!=h:
                raise ValueError('stale_input: 그림 해석이 바뀌었습니다.')
        return snapshot

    if action=='structure' and any(f['suffix']!='.json' and f['status'] in ('pending','needs_review')
                                  for f in store.files() if f['target']==target):
        raise ValueError('무료 구조 집계는 이미 분석한 자료 또는 구조화 JSON에 사용합니다. 원문은 AI 분석을 선택하세요.')
    rows=[f for f in store.files() if f['target']==target and (not options.get('file_id') or f['id']==options['file_id'])]
    rows.sort(key=lambda f:f['kind']=='exam')
    if action=='plan':rows=[]
    if resume:
        wanted_sources={t['source_id'] for t in initial if not t['source_id'].startswith('_')}
        rows=[r for r in rows if r.get('pipeline_source_id',r['id']) in wanted_sources]
    else:
        rows=[r for r in rows if action in ('read','understand') or r['status'] in ('pending','needs_review')]
    if action=='understand' and not rows:raise ValueError('이해할 자료를 먼저 추가하세요.')

    for row in rows:
        path=store.workspace/'uploads'/(row['id']+row['suffix'])
        if row['suffix']=='.json':
            ok,_,task=run('GRAPH_PROJECTION',row['id'],row['sha256'],
                lambda r=row,p=path:ingest(state,p,KINDS[r['kind']],r['exam_id'] or None),
                checkpoint=state,payload={'file_id':row['id'],'structured':True})
            if ok:row['status']='analyzed';save_row(row)
            continue
        if resume and not row.get('pipeline_source_id'):
            # Only a genuinely unfinished perception stage may be reread on resume.
            ok,_,_=run('PERCEPTION',row['id'],row['sha256'],
                lambda r=row:store._read_file(r,lambda loc,count:progress(r['name']+' · '+loc)),payload={'file_id':row['id']})
            if not ok:continue
            row=store._file(row['id']);images={}
            source=read_source(path,KINDS[row['kind']],row['exam_id'] or None,
                material_type=row['material_type'],perception_dir=store.workspace/'perception',visual_inputs=images)
            source['title']=row['name'];sid=source['id'];ih=source_fingerprint(source);sources.add(sid)
            row.update(pipeline_source_id=sid,pipeline_input_hash=ih);save_row(row)
            ledger.set(ledger.ensure('PERCEPTION',sid,ih),'complete')
            needs_initial_understanding=True
            save(root/'pipeline_state/source_snapshots'/(sid+'.json'),{'source':source,'input_hash':ih,
                'visual_inputs':{loc:[{**item,'path':str(item['path'])} for item in values] for loc,values in images.items()}})
        elif resume:
            # No perception or understanding APIs here unless the selected task is UNDERSTANDING itself.
            sid=row['pipeline_source_id'];ih=row['pipeline_input_hash'];sources.add(sid)
            check=ledger.ensure('GRAPH_PROJECTION',sid,ih,checkpoint=state,payload={'file_id':row['id']})
            try:snapshot=valid_snapshot(row)
            except Exception as exc:
                ledger.set(check,'failed_terminal',last_error={'error_type':'invalid_output','message':store.clean(str(exc))})
                touched.add(check['task_id']);continue
            source=snapshot['source'];images=snapshot.get('visual_inputs',{})
            needs_initial_understanding=False
        else:
            if not row.get('perception_manifest'):
                ok,_,task=run('PERCEPTION',row['id'],row['sha256'],
                    lambda r=row:store._read_file(r,lambda loc,count:progress(r['name']+' · '+loc)),payload={'file_id':row['id']})
                if not ok:continue
                row=store._file(row['id'])
            if action=='read':
                sources.add(row['id'])
                task=ledger.ensure('PERCEPTION',row['id'],row['sha256'])
                ledger.set(task,'complete');touched.add(task['task_id']);continue
            images={}
            try:
                source=read_source(path,KINDS[row['kind']],row['exam_id'] or None,
                    material_type=row['material_type'],perception_dir=store.workspace/'perception',visual_inputs=images)
            except Exception as exc:
                task=ledger.ensure('PERCEPTION',row['id'],row['sha256'])
                ledger.run(task,lambda:(_ for _ in ()).throw(exc),force=True);touched.add(task['task_id']);continue
            source['title']=row['name'];sid=source['id'];ih=source_fingerprint(source);sources.add(sid)
            row.update(pipeline_source_id=sid,pipeline_input_hash=ih);save_row(row)
            ledger.set(ledger.ensure('PERCEPTION',sid,ih),'complete')
            save(root/'pipeline_state/source_snapshots'/(sid+'.json'),{'source':source,'input_hash':ih,
                'visual_inputs':{loc:[{**item,'path':str(item['path'])} for item in values] for loc,values in images.items()}})
        if not source['excerpts']:
            task=ledger.ensure('UNDERSTANDING',sid,ih)
            ledger.set(task,'rejected',reason='OCR review required');touched.add(task['task_id'])
            row['status']='needs_review';save_row(row);continue

        manifest_path=root/'memory/source_manifests'/(sid+'.json')
        tasks_for_source=[t for t in initial if t['source_id']==sid]
        resume_stages={t['stage'] for t in tasks_for_source}
        needs_notes=not resume or needs_initial_understanding or bool(resume_stages & {'UNDERSTANDING','MEMORY_PERSIST','JEV_ROUTING','MEMORY_ENRICHMENT'})
        if needs_notes:
            # Construction itself must be audited without preventing later files.
            from .llm_provider import create_provider
            try:
                provider=create_provider(env_file=store.root/'.env',task='understanding',usage_path=root/'usage_log.json')
                with UnderstandingWorkspace(root/'memory',provider=provider) as workspace:
                    manifest=workspace.ingest_source(source,visual_inputs=images,
                        downstream_only=resume and not needs_initial_understanding and not bool(resume_stages & {'UNDERSTANDING','MEMORY_PERSIST'}),
                        progress=lambda label,cached:progress(row['name']+' · '+label+(' · 저장 결과 재사용' if cached else '')))
            except Exception as exc:
                task=ledger.ensure('UNDERSTANDING',sid,ih,checkpoint=manifest_path)
                ledger.run(task,lambda:(_ for _ in ()).throw(exc),force=True);touched.add(task['task_id'])
                manifest=read_json(manifest_path) if manifest_path.exists() else None
        else:manifest=read_json(manifest_path) if manifest_path.exists() else None
        row['understanding_notes']=len(manifest['note_ids']) if manifest else 0
        row['understanding_complete']=bool(manifest and manifest['coverage']['complete'])
        save_row(row)
        if manifest and manifest['coverage']['complete']:
            coarse=ledger.ensure('UNDERSTANDING',sid,ih,checkpoint=manifest_path)
            if coarse['status'] not in DONE:ledger.set(coarse,'complete',reason='all_unit_notes_committed')
        if action=='understand':continue
        graph=ledger.ensure('GRAPH_PROJECTION',sid,ih,checkpoint=state,payload={'file_id':row['id']})
        touched.add(graph['task_id'])
        if target=='teacher' and manifest and manifest['note_ids'] and (not resume or
                'TEACHER_UPDATE' in resume_stages or 'GRAPH_PROJECTION' in resume_stages):
            from .teacher_note_evidence import update_note_evidence
            ok,note_update,note_task=run('TEACHER_UPDATE',sid,ih,lambda:update_note_evidence(root,source),
                checkpoint=root/'teacher_model/state.json',payload={'file_id':row['id'],'notes_only':True})
            if ok and note_update and note_update['pending_count']:
                ledger.set(note_task,'pending',reason='note_relation_review_required')
        if not manifest or not manifest['coverage']['complete']:
            if graph['status'] not in DONE:ledger.set(graph,'pending',reason='remaining_understanding_units')
            continue
        # Rejected notes are isolated by the extractor; valid neighbouring notes remain usable.
        if resume and selected_tasks and graph['task_id'] not in selected_tasks:continue
        if graph['status'] not in DONE:
            provider=None
            def project():
                nonlocal provider
                from .llm_provider import create_provider
                provider=create_provider(env_file=store.root/'.env',task=KINDS[row['kind']],usage_path=root/'usage_log.json')
                # prepared_source is authoritative; do not repeat OCR or note generation on graph resume.
                return ingest(state,path,KINDS[row['kind']],row['exam_id'] or None,provider=provider,
                    refresh=True,material_type=row['material_type'] if row['kind']=='material' else None,
                    source_title=row['name'],prepared_source=source,prepared_manifest=manifest,prepared_visual_inputs=images,
                    analysis_progress=lambda label,cached:progress(row['name']+' · '+label))
            ok,addition,graph=run('GRAPH_PROJECTION',sid,ih,project,checkpoint=state,payload={'file_id':row['id']})
            if ok:
                committed=next((s for s in read_json(state)['sources'] if s['id']==sid),None)
                if committed and committed.get('graph_enrichment',{}).get('pending_count'):
                    ledger.set(graph,'failed_retryable',reason='graph_subtasks_pending');row['status']='needs_review';save_row(row)
            # Provider is lazily initialized inside the stage; include its audit in task diagnostics.
            if not ok and provider and graph.get('last_error'):
                graph['last_error'].update(provider=type(provider).__name__,model=provider.model,
                    provider_attempts=getattr(provider,'attempts',[]),checkpoint=str(getattr(provider,'log_path',state)),
                    input_size=sum(len(p['text']) for p in source['excerpts']))
                ledger.set(graph,graph['status'],last_error=graph['last_error'])
                if graph.get('diagnostic'):save(graph['diagnostic'],graph['last_error'])
        if graph['status']=='complete':
            row['status']='needs_review' if source.get('perception',{}).get('blocked_pages') else 'analyzed';save_row(row)

    if action not in ('read','understand','plan'):
        # Available committed graph data suffices. Failed other files are not a barrier.
        if state.exists():
            from .materials import export_material_graph
            from .question_graphs import export_question_graphs
            from .patterns import build_patterns
            ih=digest(read_json(state));sid='_'+target;sources.add(sid)
            def graph_views():
                export_material_graph(read_json(state),root/'material_graph.json')
                if target=='teacher':export_question_graphs(read_json(state),root/'question_graphs')
            view_ok,_,_=run('GRAPH_PROJECTION',sid,ih,graph_views,checkpoint=state)
            if target=='teacher':
                pattern=ledger.ensure('PATTERN_MINING',sid,ih,checkpoint=root/'patterns.json')
                if view_ok:pattern_ok,_,_=run('PATTERN_MINING',sid,ih,lambda:build_patterns(state),checkpoint=root/'patterns.json')
                else:ledger.set(pattern,'pending',reason='graph_view_unavailable');pattern_ok=False
                if action=='teacher' or resume:
                    from .teacher_incremental import update_teacher_model
                    teacher_ih=ih
                    if (root/'memory/source_manifests').exists():
                        from .teacher_primary import primary_fingerprint
                        teacher_ih=digest([ih,primary_fingerprint(root)])
                    update=ledger.ensure('TEACHER_UPDATE',sid,teacher_ih,checkpoint=root/'teacher_model/state.json')
                    synthesis=ledger.ensure('TEACHER_SYNTHESIS',sid,teacher_ih,checkpoint=root/'teacher_model/state.json')
                    touched.update([update['task_id'],synthesis['task_id']])
                    if pattern_ok or (root/'memory/source_manifests').exists():
                        ok,result,update=run('TEACHER_UPDATE',sid,teacher_ih,lambda:update_teacher_model(state,synthesize=False),checkpoint=root/'teacher_model/state.json')
                        if ok:
                            ok,result,synthesis=run('TEACHER_SYNTHESIS',sid,teacher_ih,lambda:update_teacher_model(state,synthesize=not ((root/'memory/source_manifests').exists() and primary_fingerprint(root)==synthesized_primary_hash),
                                manual_rebuild=options.get('manual_rebuild',False)),checkpoint=root/'teacher_model/state.json')
                            if ok and result and (result.get('incremental',{}).get('pending_count') or result.get('incremental',{}).get('pending_concept_ids') or result.get('incremental',{}).get('candidate_generation_pending')):
                                ledger.set(synthesis,'pending',reason='incremental_judgements_pending')
                        else:ledger.set(synthesis,'pending',reason='teacher_update_unavailable')
                    else:
                        ledger.set(update,'pending',reason='usable_patterns_required');ledger.set(synthesis,'pending',reason='teacher_update_unavailable')
        elif action in ('teacher','resume'):
            sid='_'+target;sources.add(sid)
            if target=='teacher' and (root/'memory/source_manifests').exists():
                from .teacher_primary import build_primary
                ih=digest(sorted(sources))
                _,_,u=run('TEACHER_UPDATE',sid,ih,lambda:build_primary(state,synthesize=False),checkpoint=root/'teacher_model.json')
                _,_,s=run('TEACHER_SYNTHESIS',sid,ih,lambda:build_primary(state,synthesize=primary_fingerprint(root)!=synthesized_primary_hash),checkpoint=root/'teacher_model.json')
                touched.update([u['task_id'],s['task_id']])
            else:
                for stage in ('PATTERN_MINING','TEACHER_UPDATE','TEACHER_SYNTHESIS'):
                    task=ledger.ensure(stage,sid,digest(sorted(sources)),checkpoint=root/'teacher_model/state.json')
                    ledger.set(task,'pending',reason='usable_graph_evidence_required');touched.add(task['task_id'])
            if not sources - {sid} and not (root/'teacher_model.json').exists():raise ValueError('학습자료를 먼저 추가하세요.')

    if action=='plan' or resume and any(t['stage']=='PLANNING' for t in initial):
        from .study_plan import generate_study_plan
        data=store.data(job['mode']);sid='_planning';sources.add(sid)
        plan_options={k:options.get(k,d) for k,d in [('days',7),('daily_minutes',60),('exam_format','서술형'),('max_concepts',4),('offline',True)]}
        if resume:
            saved=next(t for t in initial if t['stage']=='PLANNING');plan_options=saved['payload']
        ih=digest([data.get('model',{}),data.get('scope_dataset'),plan_options])
        def planning():
            if not data['model'] or data['model_stale']:raise ValueError('먼저 최신 Teacher Model을 생성하세요.')
            if not data['scope_material'] or not data['scope_material']['concepts']:raise ValueError('이번 시험범위 학습자료를 별도로 입력·분석하세요.')
            return generate_study_plan(store.base(job['mode'])/'teacher/teacher_model.json',
                store.base(job['mode'])/'scope/dataset.json',out=store.base(job['mode'])/'current_plan.json',**plan_options)
        run('PLANNING',sid,ih,planning,checkpoint=store.base(job['mode'])/'current_plan.json',payload=plan_options)

    current={r.get('pipeline_source_id',r['id']):r.get('pipeline_input_hash',r['sha256'])
             for r in store.files() if r['target']==target}
    global_hash=digest(read_json(state)) if state.exists() else None
    task_rows=[r for r in ledger.rows() if r['source_id'] in sources and
               (r['source_id'] not in current or r['input_hash']==current[r['source_id']]) and
               (not r['source_id'].startswith('_') or r['task_id'] in touched or r['input_hash']==global_hash)]
    # The aggregate teacher input hash can change during this one run as
    # pending graphs are committed. Only the latest aggregate task describes
    # the final snapshot; older not_started entries must not keep it partial.
    aggregate_latest={}
    for task in task_rows:
        if task['source_id']=='_teacher':
            key=task['stage']
            if key not in aggregate_latest or task['created_at']>aggregate_latest[key]['created_at']:
                aggregate_latest[key]=task
    task_rows=[task for task in task_rows if task['source_id']!='_teacher' or
               aggregate_latest[task['stage']]['task_id']==task['task_id']]
    if action=='read':task_rows=[r for r in task_rows if r['stage']=='PERCEPTION']
    structured=any(t['stage']=='GRAPH_PROJECTION' and t['status']=='complete' for t in task_rows)
    final=outcome(task_rows,structured=structured)
    if action=='read' and final=='failed_before_understanding' and any(t['status']=='complete' for t in task_rows):
        final='partial_success'
    stored=sum(t['stage']=='UNDERSTANDING' and t['status']=='complete' and bool(t['note_id']) for t in task_rows)
    if action=='plan' and any(t['status'].startswith('failed') for t in task_rows):
        final='partial_success' if data.get('model') else 'needs_review'
    job.update(status='failed' if final=='failed_before_understanding' else 'done',outcome=final,
        stage_tasks=store.clean(task_rows),stored_notes=stored,
        partial_understanding=any(r.get('understanding_notes') and not r.get('understanding_complete') for r in rows),
        pending_count=sum(t['status'] not in DONE for t in task_rows),target=target,
        step='저장 완료' if final=='complete' else '저장한 이해 노트는 바로 볼 수 있습니다. 미완료 단계만 재개하세요.')
    if action=='plan' and final!='complete':job['step']='기존 결과는 보존됐습니다. 계획 생성에 필요한 자료·설정을 확인하고 재개하세요.'
    if target=='teacher' and action in ('teacher','resume') and (root/'teacher_model.json').exists():
        from .teacher_reliability import verify_model
        model,flags=verify_model(root/'teacher_model.json')
        job.update(result_flags=flags,model_result=model.get('result'),model_revision=model['revision'],
            hypothesis_count=len(model['assessment_ideals']))
        job['step']=model.get('result',{}).get('message','교사 모델을 저장했습니다.')
    if action=='read':job['step']='텍스트·이미지 읽기 완료' if final=='complete' else '일부 자료를 읽지 못했습니다. 자료별 상태를 확인하세요.'
    if final=='failed_before_understanding':
        failures=[t for t in task_rows if t['status'].startswith('failed')]
        job['error']=failures[0].get('last_error',{}).get('message') if failures else '이해 노트를 저장하지 못했습니다.'
    for row in [r for r in store.files() if r['id'] in {v['id'] for v in rows}]:
        if row.get('pipeline_source_id') and action!='read':
            local=[t for t in task_rows if t['source_id']==row['pipeline_source_id']]
            row['pipeline_outcome']=outcome(local);save_row(row)
    return job
