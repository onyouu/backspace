"""Inspect the first nine real PDFs and import verified stage checkpoints without APIs/OCR."""
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from backspace_mvp.model import read_json
from backspace_mvp.perception import source_from_document, validate
from backspace_mvp.pipeline import digest, save
from backspace_mvp.stage_state import StageLedger, outcome
from backspace_mvp.understanding import source_fingerprint
from backspace_mvp.visual import attach_reports

ROOT=Path(__file__).resolve().parents[1]


def verify(apply=False):
    workspace=ROOT/'state/web/workspace';root=workspace/'teacher'
    files=read_json(workspace/'files.json');selected=[r for r in files if r['target']=='teacher' and r['suffix']=='.pdf'][:9]
    ledger=StageLedger(root/'pipeline_state');results=[]
    dataset_path=root/'dataset.json'
    graph_sources=read_json(dataset_path)['sources'] if dataset_path.exists() else []
    checkpoints_before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'memory').rglob('*')
                        if p.is_file() and p.suffix in ('.json','.md') and 'chroma' not in p.parts}
    with patch('urllib.request.urlopen',side_effect=AssertionError('No API in real checkpoint audit')):
        for row in selected:
            original=workspace/'uploads'/(row['id']+row['suffix'])
            sha=hashlib.sha256(original.read_bytes()).hexdigest()
            if sha!=row['sha256']:raise ValueError('Original hash mismatch')
            manifest_path=workspace/row['perception_manifest'];doc=validate(read_json(manifest_path))
            images={}
            source=attach_reports(source_from_document(original,doc,'learning_material',None,row['material_type']),doc,manifest_path,images)
            source['title']=row['name'];sid=source['id'];ih=source_fingerprint(source)
            note_manifest=root/'memory/source_manifests'/(sid+'.json')
            material_manifest=read_json(note_manifest) if note_manifest.exists() else None
            valid_units=[];stale_notes=0
            if material_manifest:
                for unit in material_manifest['units']:
                    note_path=root/'memory/notes'/(unit['id']+'.json')
                    if not note_path.exists():continue
                    note=read_json(note_path);body=note_path.with_suffix('.md').read_text(encoding='utf-8')
                    if digest(body)!=note['content_hash']:raise ValueError('Note body hash mismatch')
                    text=next((p['text'] for p in source['excerpts'] if p['locator']==unit['locator']),None)
                    if (note['source_fingerprint']!=ih or text is None or text[unit['start']:unit['end']]!=note['provenance']['quote']):
                        stale_notes+=1;continue
                    valid_units.append(unit)
            covered=[]
            for page in source['excerpts']:
                cursor=0
                for u in sorted((u for u in valid_units if u['locator']==page['locator']),key=lambda u:u['start']):
                    if u['start']>cursor and page['text'][cursor:u['start']].strip():break
                    cursor=max(cursor,u['end'])
                if not page['text'][cursor:].strip():covered.append(page['locator'])
            complete=bool(source['excerpts']) and len(covered)==len(source['excerpts'])
            graph_complete=any(s['id']==sid and source_fingerprint(s)==ih for s in graph_sources)
            record={'file_id':row['id'],'name':row['name'],'source_id':sid,'original_sha256':sha,
                'original_preserved':True,'perception_complete':True,'pages':doc['coverage']['pages'],
                'ocr_review_blocks':doc['coverage']['pending_blocks'],'accepted_text_pages':len(source['excerpts']),
                'stored_current_notes':len(valid_units),'stale_notes':stale_notes,
                'understanding_complete':complete,'understanding_partial':bool(valid_units) and not complete,
                'covered_text_pages':covered,'graph_complete':graph_complete,'api_calls':0}
            if apply:
                save(root/'pipeline_state/source_snapshots'/(sid+'.json'),{'source':source,'input_hash':ih,
                    'visual_inputs':{loc:[{**item,'path':str(item['path'])} for item in values] for loc,values in images.items()}})
                ledger.set(ledger.ensure('PERCEPTION',sid,ih,checkpoint=manifest_path),'complete',imported_checkpoint=True)
                for unit in valid_units:
                    nid=unit['id']
                    for stage in ('UNDERSTANDING','MEMORY_PERSIST'):
                        task=ledger.ensure(stage,sid,ih,note_id=nid,checkpoint=root/'memory/notes'/(nid+'.json'))
                        ledger.set(task,'complete',commit='MATERIAL_UNDERSTOOD',imported_checkpoint=True)
                    route=ledger.ensure('JEV_ROUTING',sid,ih,note_id=nid,checkpoint=note_manifest,
                        version_key=material_manifest.get('control_version'))
                    if unit.get('semantic_control',{}).get('status')=='success':ledger.set(route,'complete',imported_checkpoint=True)
                    else:ledger.set(route,'pending',reason='stored_fallback_or_no_judgment')
                    # Index was not probed: preserve existing A-MEM, queue local verification.
                    enrich=ledger.ensure('MEMORY_ENRICHMENT',sid,ih,note_id=nid,checkpoint=note_manifest,
                        version_key=digest([unit.get('semantic_control',{}).get('decision_id'),unit.get('semantic_control',{}).get('status')]))
                    ledger.set(enrich,'pending',reason='existing_index_not_probed')
                # Missing note generation is explicit, not disguised as downstream graph failure.
                if not complete:
                    task=ledger.ensure('UNDERSTANDING',sid,ih,checkpoint=note_manifest,payload={'file_id':row['id']})
                    ledger.set(task,'pending',reason='uncommitted_source_units')
                graph=ledger.ensure('GRAPH_PROJECTION',sid,ih,checkpoint=root/'checkpoints'/sid,payload={'file_id':row['id']})
                ledger.set(graph,'pending',reason='saved_projection_not_committed' if complete else 'remaining_understanding_units')
                if valid_units:
                    teacher=ledger.ensure('TEACHER_UPDATE',sid,ih,checkpoint=root/'teacher_model/state.json',payload={'file_id':row['id'],'notes_only':True})
                    ledger.set(teacher,'pending',reason='committed_note_evidence_available')
                row.update(pipeline_source_id=sid,pipeline_input_hash=ih,understanding_notes=len(valid_units),understanding_complete=complete)
                local=[t for t in ledger.rows() if t['source_id']==sid and t['input_hash']==ih]
                row['pipeline_outcome']=outcome(local)
            results.append(record)
        if apply:save(workspace/'files.json',files)
    failures=[]
    referenced=set()
    for job in (ROOT/'state/web/jobs').glob('*.json'):
        error=read_json(job).get('error') or ''
        for name in re.findall(r'output[\\/]+nvidia_runs[\\/]+([0-9a-f]{32}\.json)',error):referenced.add(name)
    for p in sorted((ROOT/'output/nvidia_runs').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        for a in read_json(p).get('attempts',[]):
            if a['status'] not in ('started','success') and (p.name in referenced or
                    a.get('elapsed_seconds',0)>1 and a.get('prompt_chars',0)>100 and
                    a['stage'].startswith(('understanding:','amem:','material:','question:'))):
                failures.append({**{k:a.get(k) for k in ('stage','model','status','elapsed_seconds','prompt_chars','max_tokens','timeout_seconds')},
                    'log':str(p),'attribution':'web_job_reference' if p.name in referenced else 'project_call_not_source_attributed'})
    unchanged=all(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==sha for name,sha in checkpoints_before.items() if (p:=Path(name)))
    report={'files':results,'file_count':len(results),'perception_complete':sum(r['perception_complete'] for r in results),
        'understanding_complete':sum(r['understanding_complete'] for r in results),
        'understanding_partial':sum(r['understanding_partial'] for r in results),
        'current_notes':sum(r['stored_current_notes'] for r in results),'graph_complete':sum(r['graph_complete'] for r in results),
        'existing_notes_and_checkpoints_unchanged':unchanged,'new_api_calls':0,
        'recent_failures':failures,'failure_counts':dict(Counter(a['stage'].split(':')[0]+':'+a['status'] for a in failures)),
        'limitation':'인식 결과·노트 저장과 원문 연결만 검증함. 노트 과학적 정확성·모든 그림의 이해를 인증하지 않음.'}
    save(ROOT/'output/pipeline_recovery/real_nine_files.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply-ledger',action='store_true')
    args=parser.parse_args();report=verify(args.apply_ledger)
    print(json.dumps({k:v for k,v in report.items() if k not in ('files','recent_failures')},ensure_ascii=False))
