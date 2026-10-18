"""Use durable, cited notes for existing-H updates while graph projection is pending."""
from pathlib import Path

from .model import read_json
from .pipeline import digest, empty_dataset
from .teacher_incremental import evidence_verifier, retrieve_memory
from .teacher_update import TeacherModelUpdateEngine, VERSION, evidence_fingerprint
from .teacher_questions import RELATION_VERSION
from .understanding import source_fingerprint


def update_note_evidence(root, source, *, control=None):
    root=Path(root)
    state_path=root/'teacher_model/state.json'
    data=read_json(root/'dataset.json') if (root/'dataset.json').exists() else empty_dataset()
    scope=read_json(state_path)['scope'] if state_path.exists() else data['scope']
    if control is None:
        from .semantic_control import SemanticControl
        control=SemanticControl(root/'teacher_model/decisions')
    # Scope/citations retain raw excerpts even if their optional graph has not committed.
    verify=evidence_verifier({'sources':[source]})
    engine=TeacherModelUpdateEngine(root/'teacher_model',scope=scope,control=control,verify_evidence=verify)
    manifest=read_json(root/'memory/source_manifests'/(source['id']+'.json'))
    if manifest['source_fingerprint']!=source_fingerprint(source):raise ValueError('stale_input: note source')
    if not engine.state['hypotheses'] and (root/'teacher_model.json').exists():
        model=read_json(root/'teacher_model.json')
        for h in model['assessment_ideals']:engine.seed_hypothesis(h,import_id=model['content_hash'])
    selected=0;pending=0;registered=0
    for unit in manifest['units']:
        note=read_json(root/'memory/notes'/(unit['id']+'.json'))
        body=(root/'memory/notes'/(unit['id']+'.md')).read_text(encoding='utf-8')
        if digest(body)!=note['content_hash']:raise ValueError('이해 노트 원문 해시가 다릅니다.')
        if note.get('review_status')=='rejected':continue
        p=note['provenance']
        record={'id':'ev_note_'+unit['id'],'kind':'understanding_note','origin_id':unit['id'],
            'details':{'content':body,'interpretation_status':'llm_understanding_needs_review',
                'source_type':note['source_type'],'question_boundary_status':note['question_boundary_status']},
            'citations':[{'source':p['source_id'],'source_sha256':p['source_sha256'],'locator':p['locator'],
                'raw_evidence':p['quote'],'char_start':p['span']['start'],'char_end':p['span']['end']}]}
        engine.register_evidence(record);registered+=1
        hypotheses,available=engine.relevant_hypotheses(record)
        if not hypotheses or engine.generic_evidence_processed(record,[h['id'] for h in hypotheses]):continue
        if all(digest(['relation',VERSION,RELATION_VERSION,evidence_fingerprint(record),h['id'],
            h['statement'],h['scope'],control.threshold_version]) in engine.state['processed'] for h in hypotheses):continue
        if selected>=engine.policy['max_changed_evidence']:
            pending+=len(hypotheses);continue
        memory=retrieve_memory(root/'memory',{'sources':[source]},p['quote'][:1000])
        result=engine.update_related_evidence(record,[h['id'] for h in hypotheses],memory=memory,
            coverage={'evidence_selected':1,'evidence_available':len(manifest['units']),
                'hypotheses_selected':len(hypotheses),'hypotheses_available':available,
                'counter_search_scope':'provided_note_only'})
        pending+=result['status']=='pending_review'
        selected+=1
    return {'registered_notes':registered,'selected_notes':selected,'pending_count':pending,
            'state_hash':engine.state['state_hash'],
            'limitation':'노트는 잠정 해석이며 문항 독립 증거로 세지 않습니다. 그래프 확보 후 모델 표시를 갱신합니다.'}
