"""Replay saved notes only. A failed small subtask stops that file, preserving A.

No OCR/Understanding generation. A --probe is explicitly NOT a full-file recovery.
"""
import argparse
import copy
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from backspace_mvp.model import read_json,validate
from backspace_mvp.pipeline import save,digest,empty_dataset
from backspace_mvp.staged import StagedExtractor
from backspace_mvp.nvidia import NvidiaProvider
from backspace_mvp.teacher_primary import collect,build_primary


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('memory/notes','memory/source_manifests','pipeline_state/source_snapshots')
        for p in (root/folder).glob('*') if p.is_file()}


def classify(message):
    text=message.lower()
    if 'quote' in text or '인용' in text:return 'quote_string_failure'
    if '강조' in text or 'emphasis' in text:return 'emphasis_contract_failure'
    if 'invalid_json' in text:return 'invalid_json'
    if 'schema' in text:return 'schema_invalid'
    if 'output_limit' in text:return 'output_limit'
    return 'actual_semantic_failure'


def sync_recovered(root,results):
    """Reflect only verified whole-file repairs in the UI ledger."""
    from backspace_mvp.stage_state import StageLedger,outcome
    root=Path(root);files_path=root.parent/'files.json'
    if not files_path.exists():return
    files=read_json(files_path);ledger=StageLedger(root/'pipeline_state')
    recovered={r['source_id'] for r in results if r['full_file_recovered']}
    failed={r['source_id']:r for r in results if not r['full_file_recovered']}
    dataset=read_json(root/'dataset.json');sources={s['id']:s for s in dataset['sources']}
    for row in files:
        sid=row.get('pipeline_source_id')
        if sid in failed:
            errors=[e for unit in failed[sid].get('diagnostics',{}).values() for e in unit.get('errors',[])]
            if errors:
                error=errors[-1];task=ledger.ensure('GRAPH_PROJECTION',sid,row['pipeline_input_hash'],checkpoint=root/'dataset.json',payload={'file_id':row['id']})
                ledger.set(task,'failed_retryable',reason='source_span_subtask_pending',last_error={
                    'type':error['type'],'message':error['reason'],'subtask':error['stage']})
                row['status']='needs_review';row['pipeline_outcome']='partial_success'
        if sid not in recovered or sid not in sources:continue
        ih=row['pipeline_input_hash'];task=ledger.ensure('GRAPH_PROJECTION',sid,ih,checkpoint=root/'dataset.json',payload={'file_id':row['id']})
        ledger.set(task,'complete',reason='all_source_span_subtasks_verified')
        row['status']='needs_review' if sources[sid].get('perception',{}).get('blocked_pages') else 'analyzed'
        row['pipeline_outcome']=outcome([t for t in ledger.rows() if t['source_id']==sid and t['input_hash']==ih])
    save(files_path,files)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='state/web/workspace/teacher')
    parser.add_argument('--probe',action='store_true');parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--source-id',action='append');parser.add_argument('--cached-only',action='store_true')
    args=parser.parse_args();root=Path(args.root);out=Path('output/graph_optional');before=hashes(root)
    data=read_json(root/'dataset.json');sources,_,_,_,_=collect(root)
    complete={s['id'] for s in data['sources'] if not s.get('graph_enrichment',{}).get('pending_count')}
    failed=[s for s in sources if s['id'] not in complete and (not args.source_id or s['id'] in args.source_id)]
    if not (out/'before.json').exists():
        save(out/'before.json',{'preserved_hashes':before,'dataset':data,'failed_source_ids':[s['id'] for s in failed]})
    def repair(source):
        sid=source['id'];manifest=read_json(root/'memory/source_manifests'/(sid+'.json'))
        images=read_json(root/'pipeline_state/source_snapshots'/(sid+'.json')).get('visual_inputs',{})
        provider=NvidiaProvider(task='learning_material',usage_path=out/(sid+'_usage.json'))
        if args.cached_only:
            def no_generation(*a,**k):raise ValueError('uncached_generation_deferred')
            provider.complete=no_generation
        ex=StagedExtractor(provider,data,copy.deepcopy(source),
            root/'checkpoints',understanding_units=manifest['units'],visual_inputs=images)
        relations=[];units=0;stopped=False
        try:
            for page in ex.pages():
                relations.extend(ex.material(page));units+=1
                print(sid+' unit '+str(units),flush=True)
                if ex.source.get('graph_enrichment',{}).get('pending_count') or args.probe:
                    stopped=True;break
            addition={**empty_dataset(),'scope':data['scope'],'sources':[ex.source],'concepts':list(ex.used.values()),
                'material_relations':list({r['id']:r for r in relations}.values()),'material_observations':ex.material_observations}
            save(out/'additions'/(sid+'.json'),addition);validate(addition)
            pending=ex.source.get('graph_enrichment',{}).get('pending_count',0)
            row={'source_id':sid,'title':source['title'],'processed_units':units,'total_notes':len(manifest['units']),
                'full_file_recovered':not stopped and pending==0,'concepts':len(addition['concepts']),
                'relations':len(relations),'pending_subtasks':pending,'diagnostics':ex.manifest.get('span_subtasks',{})}
            old=[t for t in (root/'pipeline_state/tasks').glob('*.json') if read_json(t).get('source_id')==sid and read_json(t).get('stage')=='GRAPH_PROJECTION']
            row['old_failure_classes']=sorted({classify(str(read_json(t).get('last_error',{}))) for t in old})
        except Exception as exc:
            row={'source_id':sid,'title':source['title'],'processed_units':units,'full_file_recovered':False,
                'error_type':type(exc).__name__,'error':getattr(exc,'message',str(exc))[:400],
                'error_path':list(getattr(exc,'absolute_path',[])),'diagnostics':ex.manifest.get('span_subtasks',{})}
        save(out/'repairs'/(sid+'.json'),row);return row
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(repair,s) for s in failed]
        for future in as_completed(futures):results.append(future.result())
    # Only whole-file successful replacements enter the live graph; partial A remains reusable checkpoints.
    committed=copy.deepcopy(data)
    for row in results:
        if not row['full_file_recovered']:continue
        sid=row['source_id'];addition=read_json(out/'additions'/(sid+'.json'))
        committed['sources']=[s for s in committed['sources'] if s['id']!=sid]+addition['sources']
        committed['material_observations']=[o for o in committed.get('material_observations',[]) if o['evidence'][0]['source_id']!=sid]+addition['material_observations']
        committed['material_relations']=[r for r in committed['material_relations'] if r['evidence'][0]['source_id']!=sid]+addition['material_relations']
        committed['concepts']=list({c['id']:c for c in committed['concepts']+addition['concepts']}.values())
    validate(committed)
    if committed!=data:
        save(root/'dataset_history'/('before_span_repair_'+digest(data)+'.json'),data);save(root/'dataset.json',committed)
        from backspace_mvp.materials import export_material_graph
        from backspace_mvp.question_graphs import export_question_graphs
        from backspace_mvp.patterns import build_patterns
        export_material_graph(committed,root/'material_graph.json');export_question_graphs(committed,root/'question_graphs');build_patterns(root/'dataset.json')
    model=build_primary(root/'dataset.json',synthesize=False)
    results=[read_json(p) for p in (out/'repairs').glob('*.json')]
    sync_recovered(root,results)
    report={'mode':'probe' if args.probe else 'full_file_retry_stop_on_failed_small_subtask','failed_files':len(results),
        'full_files_recovered':sum(r['full_file_recovered'] for r in results),'results':results,
        'source_notes_unchanged':before==hashes(root),'model_status':model['status'],'model_revision':model['revision'],'coverage':model['coverage']}
    save(out/'repair_report.json',report);print('FINAL '+str({k:report[k] for k in ('full_files_recovered','source_notes_unchanged','model_status')}),flush=True)


if __name__=='__main__':main()
