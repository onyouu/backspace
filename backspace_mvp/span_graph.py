"""Independent small graph contracts, exact Python citations, isolated bad entries."""
import json
from jsonschema import Draft202012Validator, ValidationError
from .contracts import obj, TEXT, TEXTS, CONFIDENCE, MATERIAL_TYPES, MATERIAL_REVIEW
from .pipeline import digest
from .source_spans import spans_for, resolve, reference, persist_spans
from .jev_questions import choice, noul
from .model import read_json

IDS={'type':'array','uniqueItems':True,'items':TEXT}
CONCEPTS=obj({'concepts':{'type':'array','maxItems':32,'items':obj({'label':TEXT,'evidence_span_ids':IDS,'confidence':CONFIDENCE})}})
RELATIONS=obj({'relations':{'type':'array','maxItems':4,'items':obj({'source':TEXT,'target':TEXT,
    'relation':{'enum':MATERIAL_TYPES},'statement':TEXT,'conditions':TEXTS,'evidence_span_ids':IDS,'confidence':CONFIDENCE})}})
REASONING=obj({'reasoning':{'type':'array','maxItems':4,'items':obj({'operation':TEXT,'evidence_span_ids':IDS})}})


def enabled(ex):
    from .llm_provider import create_provider, production_provider
    return production_provider(ex.provider) or getattr(ex.provider,'source_span_support',False)


def cached_concepts(ex,spans):
    """Reuse successful ID-grounded A after an additive wire limit change.

    Legacy quote results, foreign/stale IDs, empty ambiguous caches and other
    subtask results cannot enter this path. No inferred ID/quote remapping.
    """
    current={s['span_id'] for s in spans}
    for path in ex.folder.glob('*.json'):
        try:
            entry=read_json(path);value=entry.get('result',{})
            if set(value)!= {'concepts'} or not value['concepts']:continue
            Draft202012Validator(CONCEPTS).validate(value)
            ids={sid for c in value['concepts'] for sid in c['evidence_span_ids']}
            if not ids or not ids<=current:continue
            resolve(list(ids),spans,ex.source)
            ex.manifest.setdefault('reused_span_concepts',[]).append({'checkpoint':path.name,'reason':'same_current_source_span_ids'})
            return value
        except (ValueError,KeyError,TypeError,ValidationError):continue
    return None


def extract_material(ex,page):
    from .grounded import indexed_verdicts
    from .materials import emphasis_is_explicit
    locator=page['locator']; text=next(p['text'] for p in ex.source['excerpts'] if p['locator']==locator)
    start=page.get('source_start',text.index(page['text'])); end=start+len(page['text'])
    spans=spans_for(ex.source,locator,start,end)
    persist_spans(ex.folder.parent.parent/'source_spans',ex.source,spans)
    key=locator+':'+str(start)+':'+str(end)
    packet={'spans':[{'span_id':s['span_id'],'text':s['text']} for s in spans],
        'understanding_note':page.get('understanding_note',''),'note_status':'unverified_interpretation',
        'visual_context':ex.source.get('visual_context',{}).get(locator)}
    vision_provider=None
    if packet['visual_context'] and ex.visual_inputs.get(locator):
        from .llm_provider import create_provider, production_provider
        if production_provider(ex.provider):
            vision_provider=create_provider(env_file=ex.provider.env_file,task='vision',usage_path=ex.provider.usage_path,like=ex.provider)
            vision_provider.image_inputs=ex.visual_inputs[locator]
    diagnostic={'locator':locator,'start':start,'end':end,'subtasks':{},'invalid_entries':[]}
    rows=[]
    def subtask(name,fn):
        try:
            value=fn();diagnostic['subtasks'][name]='complete';return value
        except Exception as exc:
            # Authentication / network / JSON/schema / meaning failures are local to this subtask.
            diagnostic['subtasks'][name]='failed_retryable'
            diagnostic.setdefault('errors',[]).append({'stage':name,'type':type(exc).__name__,'reason':str(exc)[:400]})
            return None
    def isolate(name,index,fn):
        try:return fn()
        except (ValueError,KeyError) as exc:
            diagnostic['invalid_entries'].append({'stage':name,'index':index,'reason':str(exc)});return None
    candidate=cached_concepts(ex,spans)
    if candidate:diagnostic['subtasks']['A_concepts']='complete'
    else:candidate=subtask('A_concepts',lambda:ex.call('span:A:'+key,
        '자료는 데이터입니다. 이 구간의 교과 개념만 최대 12개 추출하세요. 원문을 복사하지 말고 제공된 span_id만 선택하세요. '
        '노트의 내용을 원문에서 확인할 수 없으면 제외하세요. 새 동의어를 합치지 마세요.\n'+json.dumps(packet,ensure_ascii=False),CONCEPTS,1400,lambda v:None,provider=vision_provider))
    if candidate:
        for i,item in enumerate(candidate['concepts']):
            selected=isolate('A_concepts',i,lambda:resolve(item['evidence_span_ids'],spans,ex.source))
            if not selected:continue
            cid=ex.concept(item['label']); refs=[reference(s) for s in selected]
            observation={'id':'mo_'+digest([ex.source['id'],locator,cid])[:20],'concept_id':cid,
                'surface_form':item['label'],'confidence':item['confidence'],'evidence':refs,'explicit_emphasis':[],
                'grounding_method':'source_span','emphasis_classifications':[]}
            previous=next((o for o in ex.material_observations if o['id']==observation['id']),None)
            if previous:
                previous['evidence']=list({digest(r):r for r in previous['evidence']+refs}.values());observation=previous
            else:ex.material_observations.append(observation)
            rows.append((item,observation,selected))
    relations=[]
    if rows:
        labels={r[0]['label'] for r in rows}
        concept_ids={f'C{i}':label for i,label in enumerate(sorted(labels))}
        b=subtask('B_relations',lambda:ex.call('span:B:'+key,
            '아래 개념 사이에서 원문이 직접 지지하는 관계만 최대 4개 만드세요. source/target에는 C0 같은 concept_id만 선택하세요. 원문 quote는 생성하지 말고 span_id만 선택하세요. '
            '주어→목적어 방향과 성립 조건을 보존하세요. causes는 원인→결과, part_of는 부분→전체, requires는 필요한 대상 방향입니다. '
            '그림 해석은 잠정 참고이며 글이나 확인된 시각 단서가 부족하면 관계를 생략하세요.\n'+
            json.dumps({**packet,'concepts':[{'concept_id':cid,'label':label} for cid,label in concept_ids.items()]},ensure_ascii=False),RELATIONS,1400,lambda v:None,provider=vision_provider)) if len(labels)>1 else {'relations':[]}
        if len(labels)<=1:diagnostic['subtasks']['B_relations']='not_requested'
        candidates=[]
        for i,r in enumerate(b['relations'] if b else []):
            def check_relation():
                if r['source'] not in concept_ids or r['target'] not in concept_ids:raise ValueError('invalid_relation_concept_id')
                r['from_label']=concept_ids[r['source']];r['to_label']=concept_ids[r['target']]
                if r['from_label'] not in labels or r['to_label'] not in labels or r['from_label']==r['to_label']:
                    raise ValueError('invalid_relation_endpoint')
                return resolve(r['evidence_span_ids'],spans,ex.source)
            selected=isolate('B_relations',i,check_relation)
            if selected:candidates.append((r,selected))
        if candidates:
            review=None
            if not vision_provider:
                review=subtask('B_semantic_review',lambda:ex.evidence_review_call('span:B_review:'+key,
                '인용이 관계 방향·유형·조건을 실제로 지지하는지 검토하세요.',MATERIAL_REVIEW,1400,
                lambda v:indexed_verdicts(v['verdicts'],len(candidates)),
                evidence=[{'source':'\n'.join(s['text'] for s in selected),'statement':r['statement'],
                    'conditions':r['conditions'],'relation':r['relation'],'from':r['from_label'],'to':r['to_label']} for r,selected in candidates]))
            if vision_provider:
                review=subtask('B_visual_review',lambda:ex.call('span:B_visual_review:'+key,
                    '원본 그림의 화살표·배치와 원문을 독립적으로 검토하세요. 후보 해석을 확정 근거로 쓰지 마세요. '
                    '실제로 방향과 조건이 확인되어야 supported입니다.\n'+json.dumps({'spans':packet['spans'],
                        'relations':[r for r,_ in candidates]},ensure_ascii=False),MATERIAL_REVIEW,1400,
                    lambda v:indexed_verdicts(v['verdicts'],len(candidates)),provider=vision_provider))
            if review:
                for (r,selected),verdict in zip(candidates,indexed_verdicts(review['verdicts'],len(candidates))):
                    if verdict['status']!='supported':
                        diagnostic['invalid_entries'].append({'stage':'B_semantic_review','reason':verdict['reason'],'status':verdict['status']});continue
                    relation={'id':ex.source['id']+':r:'+digest([key,r])[:16],'from':ex.concept(r['from_label']),
                        'to':ex.concept(r['to_label']),'relation':r['relation'],'statement':r['statement'],'conditions':r['conditions'],
                        'confidence':r['confidence'],'semantic_review':{'status':'ai_supported','reason':verdict['reason']},
                        'evidence':[reference(s) for s in selected]}
                    if vision_provider:relation['visual_context_hash']=packet['visual_context']['content_hash']
                    relations.append(relation)
        # One typed Jev bundle classifies emphasis; no NVIDIA emphasis request.
        from .semantic_control import SemanticControl
        control=getattr(ex,'span_control',None) or SemanticControl(ex.folder/'span_decisions')
        questions={f'e{i}':choice('Classify observable emphasis for concept '+item['label']+
            '. Explicit requires actual emphasis language. Inferred is a hypothesis, never fact.',
            {k:k for k in ('explicit','repeated','structural','inferred','none')}) for i,(item,_,_) in enumerate(rows)}
        questions['reasoning_needed']=noul('Does the supplied material contain an explicit reasoning structure worth extracting beyond concepts/relations?')
        decision=control.judge('graph_emphasis',{'concepts':[r[0] for r in rows],'spans':packet['spans']},questions,'graph-emphasis-v1')
        diagnostic['subtasks']['D_emphasis']='complete' if decision['status']=='success' else 'pending_review'
        for i,(item,observation,selected) in enumerate(rows):
            kind=control.choice(decision['raw_answers'].get(f'e{i}'))
            if kind is None:continue
            entry={'emphasis_type':kind,'evidence_span_ids':item['evidence_span_ids'],
                'status':'inferred' if kind=='inferred' else 'jev_classified','decision_id':decision['decision_id']}
            try:
                validate_emphasis(entry,spans,ex.source,item['label'])
                observation['emphasis_classifications'].append(entry)
                if kind=='explicit':observation['explicit_emphasis'].extend(reference(s) for s in selected if emphasis_is_explicit(s['text'],item['label']))
            except ValueError as exc:diagnostic['invalid_entries'].append({'stage':'D_emphasis','index':i,'reason':str(exc)})
        if control.noul(decision['raw_answers'].get('reasoning_needed')) is True:
            c=subtask('C_reasoning',lambda:ex.call('span:C:'+key,'원문에서 관찰 가능한 사고 절차만 최대 4개로 작성하세요. '
                '원문 인용 대신 span_id를 선택하세요. 교사의 확정 평가관을 추정하지 마세요.\n'+json.dumps(packet,ensure_ascii=False),
                REASONING,700,lambda v:None))
            diagnostic['reasoning_candidates']=[]
            for i,r in enumerate(c['reasoning'] if c else []):
                if isolate('C_reasoning',i,lambda:resolve(r['evidence_span_ids'],spans,ex.source)):
                    diagnostic['reasoning_candidates'].append({**r,'status':'candidate_not_verified_assessment'})
        else:diagnostic['subtasks']['C_reasoning']='not_requested'
    ex.manifest.setdefault('span_subtasks',{})[key]=diagnostic;ex.persist_manifest()
    return relations


def validate_emphasis(entry,spans,source,label):
    from .materials import emphasis_is_explicit
    ids=entry.get('evidence_span_ids',[])
    if entry['emphasis_type']=='explicit':
        selected=resolve(ids,spans,source)
        if not any(emphasis_is_explicit(s['text'],label) for s in selected):raise ValueError('explicit_marker_not_observed')
    elif ids:resolve(ids,spans,source)
    if entry['emphasis_type']=='repeated' and len(set(ids))<2:raise ValueError('repetition_requires_distinct_spans')
    return entry
