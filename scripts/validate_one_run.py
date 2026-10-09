"""Actual saved corpus verification. Never regenerates OCR or Understanding Notes."""
import argparse
from pathlib import Path
from backspace_mvp.pipeline import save
from backspace_mvp.model import read_json
from backspace_mvp.teacher_primary import build_primary, collect
from backspace_mvp.teacher_reliability import verify_model
from scripts.validate_graph_optional import hashes


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['graphless','enrich','audit'],required=True)
    args=parser.parse_args();root=Path('state/web/workspace/teacher');out=Path('output/one_run')
    if args.phase=='graphless':
        sources,records,eligible,rejected,routes=collect(root)
        if not (out/'baseline.json').exists():
            save(out/'baseline.json',{'hashes':hashes(root),'model':read_json(root/'teacher_model.json'),
                'nvidia_logs':[p.name for p in Path('output/nvidia_runs').glob('*.json')],
                'source_ids':[s['id'] for s in sources],'valid_notes':len(records),'eligible_notes':eligible})
            save(out/'state_before.json',read_json(root/'teacher_model/state.json'))
        model=build_primary(root/'dataset.json',include_graph=False)
        _,flags=verify_model(root/'teacher_model.json')
        save(out/'graphless_model.json',model)
        save(out/'graphless_result.json',{'flags':flags,'status':model['status'],'counts':model['counts'],
            'coverage':model['coverage'],'result':model['result'],'notes_unchanged':hashes(root)==read_json(out/'baseline.json')['hashes']})
        print('GRAPHLESS',model['status'],model['counts'],model['result']['kind'],flush=True)
    elif args.phase=='enrich':
        model=build_primary(root/'dataset.json',synthesize=False)
        save(out/'enriched_model.json',model)
        print('ENRICHED',model['status'],model['counts'],flush=True)
    else:
        before=read_json(out/'baseline.json');events=[]
        for p in Path('output/nvidia_runs').glob('*.json'):
            if p.name not in before['nvidia_logs']:
                for a in read_json(p).get('attempts',[]):
                    events.append({'log':p.name,**{k:a.get(k) for k in ('stage','status','elapsed_seconds','model','retry_index')}})
        save(out/'audit.json',{'nvidia_calls':len(events),'nvidia_failures':sum(x['status']!='success' for x in events),
            'events':events,'notes_unchanged':hashes(root)==before['hashes']})
        print('AUDIT',len(events),flush=True)


if __name__=='__main__':main()
