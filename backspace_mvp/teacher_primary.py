"""Notes are primary evidence; graphs are independently versioned enrichment."""
import copy
import json
import os
from jsonschema import ValidationError
from pathlib import Path
from .model import read_json
from .pipeline import digest, empty_dataset, save
from .understanding import source_fingerprint
from .teacher_update import TeacherModelUpdateEngine, compact, now
from .teacher_questions import (prefilter_questions, PREFILTER_VERSION, sufficient_questions, SUFFICIENT_VERSION,
    novelty_questions, NOVELTY_VERSION, integration_questions, INTEGRATION_VERSION)

from .teacher_reliability import note_bundles, result_summary, verify_model, CLOSED

VERSION = 'teacher-model-notes-1'


def collect(root):
    """Read canonical bodies only, never regenerate OCR, notes or search metadata."""
    root = Path(root); sources = []; records = {}; eligible = 0; rejected = []; routes = {}
    files_path=root.parent/'files.json';active=None;active_files={}
    if files_path.exists():
        files=read_json(files_path)
        if isinstance(files,dict):files=files.get('files',[])
        active={r.get('pipeline_source_id') for r in files if r.get('target')=='teacher'}
        active_files={r.get('pipeline_source_id'):r for r in files if r.get('target')=='teacher'}
    for path in sorted((root/'memory/source_manifests').glob('*.json')):
        manifest = read_json(path)
        if active is not None and manifest['source_id'] not in active:continue
        eligible+=len(manifest['units'])
        snapshot = root/'pipeline_state/source_snapshots'/(manifest['source_id']+'.json')
        if not snapshot.exists(): continue
        source = read_json(snapshot)['source']
        current=active_files.get(source['id'],{})
        if current and (current.get('sha256')!=source['sha256'] or
            current.get('perception_hash') and current['perception_hash']!=source.get('perception',{}).get('content_hash') or
            any(source.get('visual_context',{}).get(loc,{}).get('content_hash')!=version for loc,version in current.get('visual_pages',{}).items())):
            rejected.append({'source':source['id'],'reason':'current_transcription_changed'});continue
        if source_fingerprint(source) != manifest['source_fingerprint']:
            rejected.append({'source': source['id'], 'reason': 'stale_manifest'}); continue
        sources.append(source)
        for unit in manifest['units']:
            try:
                meta = read_json(root/'memory/notes'/(unit['id']+'.json'))
                body = (root/'memory/notes'/(unit['id']+'.md')).read_text(encoding='utf-8')
                if meta.get('review_status') == 'rejected': raise ValueError('human_rejected')
                if meta['source_fingerprint'] != manifest['source_fingerprint'] or digest(body) != meta['content_hash']:
                    raise ValueError('stale_note')
                p = meta['provenance']; raw = next(x['text'] for x in source['excerpts'] if x['locator']==p['locator'])
                if raw[p['span']['start']:p['span']['end']] != p['quote']: raise ValueError('provenance_mismatch')
                eid = 'ev_note_'+unit['id']
                records[eid] = {'id':eid, 'kind':'understanding_note', 'origin_id':unit['id'],
                    'details':{'content':body, 'topic':meta.get('topic',unit.get('topic',[])),
                        'interpretation_status':'llm_understanding_needs_review', 'source_type':meta['source_type'],
                        'question_boundary_status':meta['question_boundary_status']},
                    'citations':[{'source':source['id'], 'source_sha256':source['sha256'], 'locator':p['locator'],
                        'raw_evidence':p['quote'], 'char_start':p['span']['start'], 'char_end':p['span']['end']}]}
                routes[eid] = unit.get('semantic_control',{}).get('final_route',{})
            except (ValueError, OSError, KeyError, StopIteration) as exc:
                rejected.append({'note':unit['id'], 'reason':str(exc)[:160]})
    return sources, records, eligible, rejected, routes


def primary_fingerprint(root):
    sources, records, eligible, rejected, _ = collect(root)
    return digest([[(s['id'],source_fingerprint(s)) for s in sources],records,eligible,rejected])


def build_primary(state, *, provider=None, jev_provider=None, control=None, synthesize=True, policy=None, include_graph=True, **_):
    from .teacher_incremental import evidence_verifier, retrieve_memory, write_artifact
    from .semantic_control import SemanticControl
    from .contracts import obj, TEXT, TEXTS
    root = Path(state).resolve().parent
    optional_errors=[]
    try:
        from .model import validate
        data = validate(read_json(state)) if Path(state).exists() else empty_dataset()
    except (ValueError,OSError,KeyError,ValidationError):
        data=empty_dataset()
        previous=root/'teacher_model.json'
        if previous.exists():data['scope']=read_json(previous)['scope']
        optional_errors.append({'artifact':'dataset_graph','status':'unavailable_or_stale'})
    if not include_graph:
        scope=data['scope'];data=empty_dataset();data['scope']=scope
    sources, registry, eligible, rejected, routes = collect(root)
    all_sources = {s['id']:s for s in [*data['sources'],*sources]}
    current_sources={s['id']:s for s in sources}
    invalid_sources={r['source'] for r in rejected if r.get('source')}
    valid_graph_sources={s['id'] for s in data['sources'] if s['id'] not in invalid_sources and
        (s['id'] not in current_sources or source_fingerprint(s)==source_fingerprint(current_sources[s['id']]))}
    graph_ids = set(); graph_complete = set()
    # Direct dataset evidence does not require patterns/material views to succeed.
    for observation in data.get('material_observations',[]):
        if not all(r['source_id'] in valid_graph_sources for r in observation['evidence']):continue
        refs = observation['evidence']; eid = 'ev_graph_'+observation['id']
        citations = []
        for r in refs:
            src = all_sources[r['source_id']]; text = next(p['text'] for p in src['excerpts'] if p['locator']==r['locator'])
            start = r.get('start_offset',text.index(r['quote']))
            citations.append({'source':src['id'],'source_sha256':src['sha256'],'locator':r['locator'],
                'raw_evidence':r['quote'],'char_start':start,'char_end':start+len(r['quote'])})
            graph_ids.add(src['id'])
        registry[eid] = {'id':eid,'kind':'material_concept','origin_id':observation['concept_id'],
            'details':{'id':observation['concept_id'],'observation':observation},'citations':citations}
    for s in data['sources']:
        if s['id'] in valid_graph_sources and not s.get('graph_enrichment',{}).get('pending_count'): graph_complete.add(s['id'])
    for q in data.get('questions',[]):
        if not all(r['source_id'] in valid_graph_sources for r in q['evidence']):continue
        citations=[]
        for r in q['evidence']:
            src=all_sources[r['source_id']]; text=next(p['text'] for p in src['excerpts'] if p['locator']==r['locator'])
            at=r.get('start_offset',text.index(r['quote']))
            citations.append({'source':src['id'],'source_sha256':src['sha256'],'locator':r['locator'],
                'raw_evidence':r['quote'],'char_start':at,'char_end':at+len(r['quote'])});graph_ids.add(src['id'])
        eid='ev_question_'+q['id']
        registry[eid]={'id':eid,'kind':'question','origin_id':q['id'],'details':{'question_id':q['id'],
            'exam_id':q['exam_id'],'answer_requirements':q.get('answer_requirements',[]),'nodes':[]},'citations':citations}
    control=control or SemanticControl(root/'teacher_model/decisions',provider=jev_provider)
    engine=TeacherModelUpdateEngine(root/'teacher_model',scope=data['scope'],control=control,policy=policy,
        verify_evidence=evidence_verifier({'sources':list(all_sources.values())}))
    with engine.transaction():
        old_path=root/'teacher_model.json'
        if old_path.exists() and not engine.state['hypotheses']:
            old=read_json(old_path)
            for h in old.get('assessment_ideals',[]): engine.seed_hypothesis(h,import_id=old['content_hash'])
        engine.reconcile_evidence(registry)
        for e in registry.values(): engine.register_evidence(e)
        changed=0
        for e in registry.values():
            hs,available=engine.relevant_hypotheses(e)
            if not hs or engine.generic_evidence_processed(e,[h['id'] for h in hs]): continue
            if changed>=engine.policy['max_changed_evidence']: break
            engine.update_related_evidence(e,[h['id'] for h in hs],
                memory=retrieve_memory(root/'memory',{'sources':list(all_sources.values())},e['citations'][0]['raw_evidence'][:800]),
                coverage={'evidence_selected':1,'evidence_available':len(registry),
                    'hypotheses_selected':len(hs),'hypotheses_available':available,'counter_search_scope':'provided_evidence_only'})
            changed+=1
        # Only small, Jev-selected note bundles can ask NVIDIA for a NEW candidate.
        notes=[e for e in registry.values() if e['kind']=='understanding_note' and routes.get(e['id'],{}).get('teacher_signal') is not False
            and sum(c.isalpha() for c in e['citations'][0]['raw_evidence'])>=20]
        bundles=note_bundles(notes,routes,data['scope'])
        current_clusters={};selection={'valid_notes':len([e for e in registry.values() if e['kind']=='understanding_note']),
            'route_teacher_signal':sum(routes.get(e['id'],{}).get('teacher_signal') is True for e in notes),
            'eligible_notes':len(notes),'eligible_bundles':len(bundles),'selected_evidence_ids':[],
            'retrieved_note_ids':[],'generation_requests':0}
        # Budget only eligible, unfinished bundles; a single-source topic consumes no slot.
        budget=max(1,int(os.environ.get('TEACHER_BUNDLE_BUDGET','12')));examined=0;generated=0
        for identity,topic,rows,selected in bundles:
            previous_cluster=engine.state['clusters'].get(identity,{})
            current_clusters[identity]=previous_cluster or {'status':'budget_deferred'}
            if previous_cluster.get('status') in CLOSED: continue
            if not synthesize or examined>=budget: continue
            examined+=1
            selection['selected_evidence_ids'].extend(e['id'] for e in selected)
            packet={'evidence':selected,'existing_hypotheses':[compact(h) for h in engine.state['hypotheses'].values()][:4],
                'coverage':{'selected':len(selected),'available':len(rows),'counter_search_scope':'provided_notes_only'}}
            packet['related_memory']=retrieve_memory(root/'memory',{'sources':list(all_sources.values())},topic,max_chars=1200)
            selection['retrieved_note_ids'].extend(n['id'] for n in packet['related_memory'].get('notes',[]))
            gate=control.judge('teacher_notes_prefilter',packet,prefilter_questions(len(selected)),PREFILTER_VERSION)
            signal=control.noul(gate['raw_answers'].get('teacher_signal'))
            needs_interpretation=False
            if gate['status']=='success' and signal is None:
                from .jev_questions import noul
                ambiguity=control.judge('teacher_notes_ambiguity',{
                    'evidence':[{'id':e['id'],'citations':e['citations']} for e in selected],
                    'existing_hypotheses':packet['existing_hypotheses'],
                    'scope':'Only observable requirements in these teaching materials; not uniqueness against other teachers.'},
                    {'observable_request':noul('Do at least two supplied sources explicitly ask learners to explain, compare, infer a cause, justify, or interpret data? Use the original task wording; generic facts alone are not requests.'),
                     'needs_interpretation':noul('Is a bounded generative comparison of these explicit task requests needed to propose a conditional common assessment pattern not explained by existing_hypotheses? This is permission to examine a candidate, not acceptance of that candidate.')},
                    'notes-ambiguity-v1')
                needs_interpretation=(ambiguity['status']=='success' and all(control.noul(ambiguity['raw_answers'].get(k)) is True
                    for k in ('observable_request','needs_interpretation')))
                packet['ambiguity_decision_id']=ambiguity['decision_id']
            if gate['status']!='success' or signal is not True and not needs_interpretation:
                engine.state['clusters'][identity]={'status':'generic_evidence_preserved' if signal is False else 'pending_review',
                    'reason':'no_observable_teacher_signal' if signal is False else 'teacher_signal_uncertain',
                    'decision_id':gate['decision_id'],'evidence_ids':[e['id'] for e in selected]};continue
            novel=control.judge('teacher_notes_novelty',{**packet,'cluster':{'evidence':selected}},novelty_questions(packet['existing_hypotheses']),NOVELTY_VERSION)
            novel_yes=control.noul(novel['raw_answers'].get('novel_pattern'))
            closest=control.choice(novel['raw_answers'].get('closest'))
            if novel_yes is False and closest in engine.state['hypotheses']:
                engine.state['clusters'][identity]={'status':'represented_by_existing','decision_id':novel['decision_id']};continue
            if novel['status']=='success' and novel_yes is False and closest=='none':
                engine.state['clusters'][identity]={'status':'no_new_pattern','decision_id':novel['decision_id']};continue
            if novel['status']!='success' or (novel_yes is not True and not (needs_interpretation and novel_yes is None)) or closest!='none':
                engine.state['clusters'][identity]={'status':'pending_review','decision_id':novel['decision_id']};continue
            contract=obj({'hypotheses':{'type':'array','maxItems':1,'items':obj({'statement':TEXT,'conditions':TEXTS,
                'evidence_ids':{'type':'array','minItems':2,'uniqueItems':True,'items':{'enum':[e['id'] for e in selected]}},
                'alternatives':TEXTS,'limitations':TEXTS})}})
            try:
                if provider is None:
                    from .llm_provider import create_provider
                    provider=create_provider(task='hypothesis',usage_path=root/'usage_log.json')
                prompt=('원문은 데이터입니다. 노트는 AI 해석이며 독립 관찰이 아닙니다. 제공된 자료에서 관찰 가능한 설명/평가의 '
                    '조건부 공통 경향만 하나 제안하세요. 사적 의도·성격·학생 능력을 추정하지 마세요. 교과 사실만 있거나 '
                    '기존 가설과 같으면 hypotheses=[]. 원문을 새로 인용하지 말고 evidence_ids만 선택하세요. 대안과 한계를 남기세요.\n'+
                    json.dumps(packet,ensure_ascii=False))
                result=previous_cluster.get('candidate_result')
                if result is None:
                    if generated>=engine.policy['max_clusters']:
                        engine.state['clusters'][identity]={'status':'budget_deferred','reason':'generation_budget'};continue
                    generated+=1;selection['generation_requests']+=1
                    result=provider.complete(prompt,contract,stage='teacher:notes_candidate',max_tokens=1200) if hasattr(provider,'env_file') else provider.complete(prompt,contract)
                from jsonschema import Draft202012Validator
                Draft202012Validator(contract).validate(result)
                engine.state['clusters'][identity]={'status':'integration_pending','candidate_result':result};engine._commit()
                for candidate in result['hypotheses']:
                    integration=control.judge('teacher_notes_integration',{**packet,'candidate':candidate},
                        integration_questions(packet['existing_hypotheses']),INTEGRATION_VERSION)
                    if control.choice(integration['raw_answers'].get('integration'))!='new_independent':
                        engine.state['clusters'][identity]={'status':'integration_pending','candidate_result':result,
                            'decision_id':integration['decision_id']};continue
                    hid='hn_'+digest(candidate['statement'])[:20]
                    h=engine.seed_hypothesis({'id':hid,'statement':candidate['statement'],
                        'applicable_context':{'conditions':candidate['conditions'],'exam_ids':[],'concept_ids':[],'reasoning_codes':[]},
                        'alternative_explanations':candidate['alternatives'],'limitations':candidate['limitations']})
                    for eid in candidate['evidence_ids']: engine.update_evidence(registry[eid],hid,coverage=packet['coverage'])
                    if h['statistics'].get('source_diversity',0)>=2:
                        sufficient=control.judge('teacher_notes_sufficient',{'hypothesis':compact(h),
                            'evidence':selected,'statistics':h['statistics'],'coverage':packet['coverage']},sufficient_questions(),SUFFICIENT_VERSION,hypothesis_ids=[hid])
                        h['note_sufficiency']={'decision_id':sufficient['decision_id'],
                            'accepted':control.noul(sufficient['raw_answers'].get('sufficient')) is True}
                if not result['hypotheses'] or any(h['statement']==c['statement'] for h in engine.state['hypotheses'].values() for c in result['hypotheses']):
                    engine.state['clusters'][identity]={'status':'processed','decision_id':gate['decision_id'],'candidate_result':result}
            except (ValueError,OSError,TimeoutError,KeyError,ValidationError) as exc:
                engine.state['clusters'][identity]={**engine.state['clusters'].get(identity,{}),'status':'failed_retryable','reason':type(exc).__name__}
        current_clusters={identity:engine.state['clusters'].get(identity,value) for identity,value in current_clusters.items()}
        for key in ('selected_evidence_ids','retrieved_note_ids'):selection[key]=sorted(set(selection[key]))
        # Preserve the last synthesis selection on an enrichment-only pass.
        if synthesize: engine.state['notes_selection']=selection
        else: selection=engine.state.get('notes_selection',selection)
        ideals=[]
        for hid,h in engine.state['hypotheses'].items():
            previous=copy.deepcopy(h);engine._statistics(h);stats=h['statistics']
            supports=[registry[eid] for eid in h['supporting_evidence'] if eid in registry]
            pending_scope=any(x['status']=='pending_review' for x in h['scope_candidates'])
            readiness='provisional'
            if stats.get('unresolved_strong_contradiction') or pending_scope: readiness='needs_review'
            elif h.get('note_sufficiency',{}).get('accepted') and stats.get('source_diversity',0)>=2 and h['scope']['conditions']:
                readiness='usable'
            if h['lifecycle_status']=='active' and stats.get('independent_questions',0)>=2: readiness='well_supported'
            if h['lifecycle_status'] in ('rejected','retired'): readiness='needs_review'
            graph_support='available' if any(e['kind']!='understanding_note' for e in supports) else 'pending'
            h.update(readiness=readiness,graph_support=graph_support)
            engine._validate('teacher_hypothesis_state.schema.json',h)
            engine._change(hid,previous,'readiness_or_graph_enrichment',None,None,digest([hid,h,engine.state['version']]))
            legacy=h['legacy'];ideals.append({'id':hid,'statement':h['statement'],'status':readiness,'readiness':readiness,
                'graph_support':graph_support,'lifecycle_status':h['lifecycle_status'],'review_priority':'provisional_support' if readiness in ('usable','well_supported') else 'uncertain_judgement_review',
                'applicable_context':{'conditions':h['scope']['conditions'],'exam_ids':h['scope']['exam_ids'],'concept_ids':h['concept_ids'],'reasoning_codes':h['reasoning_codes']},
                'supporting_evidence':[{'evidence_id':e['id'],'reason':'저장된 Jev 관계 판단'} for e in supports],
                'counter_evidence':[{'evidence_id':eid,'reason':'저장된 반례 판단'} for eid in h['contradicting_evidence'] if eid in registry],
                'supporting_question_ids':[e['origin_id'] for e in supports if e['kind']=='question'],
                'counter_evidence_status':'identified' if h['contradicting_evidence'] else 'no_counter_identified_in_provided_context',
                'alternative_explanations':legacy.get('alternative_explanations',[]),'limitations':legacy.get('limitations',[]),
                'judgement':None,'incremental_state':{k:h[k] for k in ('scope','statistics','scope_candidates')}})
        engine._commit()
    applied={(r['evidence_id'],r['hypothesis_id']) for r in engine.state['relations'].values() if r['status']=='applied'
        and r['evidence_id'] in registry and engine.state['evidence'][r['evidence_id']]['fingerprint']==r['evidence_hash']}
    eligible_pairs=sum(engine.relevant_hypotheses(e)[1] for e in registry.values())
    # Reuse compatible optional views and scores; their absence never blocks the model.
    optional={}
    from .scoring import checked_artifact
    for name,schema in [('patterns','patterns.schema.json'),('teacher_scores','teacher_scores.schema.json')]:
        try:
            if invalid_sources:raise ValueError('optional_graph_inputs_changed')
            value=checked_artifact(root/(name+'.json'),schema,data['scope'])
            input_hash=value.get('dataset_hash',value.get('inputs',{}).get('dataset_hash'))
            if input_hash==digest(data):optional[name]=value
        except (ValueError,OSError,KeyError,ValidationError):optional_errors.append({'artifact':name,'status':'unavailable_or_stale'})
    importance=[]
    score_index={r['concept_id']:r for r in optional.get('teacher_scores',{}).get('concept_scores',[])}
    for c in data['concepts']:
        score=score_index.get(c['id']);salience=score.get('teacher_salience') if score else None
        importance.append({'concept_id':c['id'],'label':c['label'],'aliases':c['aliases'],'teacher_importance':salience,
            'status':'provisional' if salience is not None else 'not_scored','judgement':score,
            'material_observations':None,'question_observations':[]})
    dominant={k:[r for r in optional.get('patterns',{}).get('patterns',{}).get(k,[]) if
        r['mode']=='reasoning_structure' and r['is_repeated'] and r['meets_min_support']] for k in ('nodes','edges','paths','subgraphs')}
    source_ids={s['id'] for s in sources}|invalid_sources; note_sources={e['citations'][0]['source'] for e in registry.values() if e['kind']=='understanding_note'}
    coverage={'understanding':{'completed':len([e for e in registry.values() if e['kind']=='understanding_note']),'eligible':eligible},
        'teacher_evidence':{'completed':len(note_sources),'eligible':len(source_ids)},
        'jev_relation':{'completed':len(applied),'eligible':eligible_pairs,'unit':'evidence_hypothesis_pairs',
            'catalog_entries':len(registry),'status':'not_requested_no_hypotheses' if not eligible_pairs else 'judged_or_pending'},
        'graph':{'observed_count':len(graph_ids&source_ids),'eligible_count':len(source_ids),'completed_count':len(graph_complete&source_ids)},
        'pattern_coverage':{'included_questions':len(data['questions'])}}
    status='not_ready' if not registry else 'provisional'
    if ideals and all(h['readiness']=='needs_review' for h in ideals): status='needs_review'
    elif any(h['readiness']=='well_supported' for h in ideals): status='well_supported'
    elif any(h['readiness']=='usable' for h in ideals): status='usable'
    body={'schema_version':'1.0','architecture_version':'teacher-intelligence-0.1','implementation_milestone':'0.6',
        'model_version':VERSION,'scope':data['scope'],'status':status,'actual_student_behavior':'not_observed',
        'inputs':{'dataset_hash':digest(data),'primary_evidence_hash':primary_fingerprint(root),'graph_hash':digest(data)},
        'coverage':coverage,'counts':{'concepts':len(data['concepts']),'scored_concepts':sum(c['teacher_importance'] is not None for c in importance),'questions':len(data['questions']),
            'hypotheses':len(ideals),'scored_hypotheses':len([h for h in ideals if h['readiness'] in ('usable','well_supported')])},
        'concept_importance':importance,'dominant_reasoning':dominant,'assessment_ideals':ideals,
        'evidence_registry':list(registry.values()),'material_relations':[],'material_sources':list(all_sources.values()),'input_question_graphs':[],
        'reasoning_basis':'notes_primary_graph_optional','score_meaning':'observed_evidence_not_probability',
        'limitations':['이해 노트는 잠정 해석입니다. 학생 실제 수행은 미관찰입니다.','지도 빈도는 완료된 지도 범위에서만 해석합니다.'],
        'rejected_evidence':rejected,'optional_errors':optional_errors,
        'result':result_summary(registry,ideals,current_clusters,selection),
        'quality':{'understanding':{'total':eligible,'valid':coverage['understanding']['completed'],
            'rejected':sum(r.get('reason')=='human_rejected' for r in rejected),
            'stale_or_invalid':eligible-coverage['understanding']['completed']-sum(r.get('reason')=='human_rejected' for r in rejected)},
            'teacher_evidence':{'registered':len(registry),'accepted':len({e['evidence_id'] for h in ideals for e in h['supporting_evidence']}),
                'supporting_pairs':sum(r['relation'] in ('reinforces','broadens_scope') for r in engine.state['relations'].values() if (r['evidence_id'],r['hypothesis_id']) in applied),
                'unrelated_pairs':sum(r['relation']=='unrelated' for r in engine.state['relations'].values() if (r['evidence_id'],r['hypothesis_id']) in applied)},
            'clusters':[{'id':k,**v} for k,v in current_clusters.items()]},
        'incremental':{'version':engine.state['version'],'state_hash':engine.state['state_hash'],
            'pending_count':sum(not p['resolved'] for p in engine.state['pending'].values()),'candidate_generation_pending':sum(x['status'] in ('failed_retryable','integration_pending','budget_deferred') for x in current_clusters.values()),
            'lifecycle_counts':{s:sum(h['lifecycle_status']==s for h in engine.state['hypotheses'].values()) for s in ('candidate','active','weak','contested','retired','rejected')},
            'graph_support_pending':sum(h['graph_support']=='pending' for h in ideals)}}
    write_artifact(root/'teacher_model.json',body,'teacher_model.schema.json')
    model,_=verify_model(root/'teacher_model.json')
    return model
