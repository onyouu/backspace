"""Small real-note replay benchmark. Writes only into an isolated output directory.

Live requests require --live. This is not a full Teacher Model quality benchmark.
"""
import argparse
import copy
import json
import statistics
import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backspace_mvp.model import read_json
from backspace_mvp.pipeline import digest,save
from backspace_mvp.understanding import write_text
from backspace_mvp.amem_adapter import BackspaceMemorySystem,NvidiaMemoryController
from backspace_mvp.llm_provider import create_provider
from backspace_mvp.jev import JevProvider
from backspace_mvp.semantic_control import SemanticControl


def metrics(nvidia,jev):
    nv=nvidia.attempts; jv=jev.attempts if jev else []
    tokens=[a['usage']['prompt_tokens'] for a in nv if isinstance(a.get('usage'),dict) and 'prompt_tokens' in a['usage']]
    return {'nvidia_call_count':len(nv),'jev_call_count':len(jv),
        'nvidia_timeout_count':sum(a['status']=='timeout' for a in nv),
        'nvidia_output_limit_count':sum(a['status']=='output_limit' for a in nv),
        'average_nvidia_input_tokens':statistics.mean(tokens) if tokens else None,
        'average_nvidia_latency_seconds':statistics.mean(a['elapsed_seconds'] for a in nv) if nv else None,
        'total_nvidia_latency_seconds':sum(a['elapsed_seconds'] for a in nv),
        'total_jev_latency_seconds':sum(a['elapsed_seconds'] for a in jv),
        'estimated_cost':None,'cost_status':'provider_prices_and_charges_not_measured'}


def run(note_path,out):
    record=read_json(note_path);content=note_path.with_suffix('.md').read_text(encoding='utf-8')
    if digest(content)!=record['content_hash']:raise ValueError('Canonical note hash mismatch')
    if record.get('review_status')=='rejected':raise ValueError('Rejected note cannot be a benchmark candidate')
    out.mkdir(parents=True,exist_ok=True)
    summary={'scope':'metadata_and_evolution_only_on_identical_real_note_replay',
        'source':record['provenance'],'original_note_hash':digest(content),
        'teacher_output_regression':'full graph/model/plan chain verified in mocks only; not measured on real corpus',
        'limitations':['The understanding note is unreviewed AI interpretation.',
            'Same original page replay, not a second independent evidence source.',
            'Graph projection is judged but not executed in this microbenchmark.',
            'A zero timeout count on this small sample does not prove corpus-wide timeout reduction.']}
    for mode in ('baseline','controlled'):
        folder=out/mode/'memory'
        save(folder/'notes'/(record['id']+'.json'),record)
        write_text(folder/'notes'/(record['id']+'.md'),content)
        save(folder/'source_manifests'/('benchmark.json'),{
            'source_id':record['provenance']['source_id'],'source_fingerprint':record['source_fingerprint'],
            'note_ids':[record['id']]})
        nv=create_provider(task='memory_metadata',usage_path=out/mode/'usage_log.json')
        controller=NvidiaMemoryController(nv,folder/'metadata_checkpoints')
        system=BackspaceMemorySystem(folder,controller)
        metadata={k:copy.deepcopy(v) for k,v in record.items() if k not in ('amem','upstream','content_hash')}
        metadata['id']='un_'+digest(['jev-live-replay',record['id'],mode])[:28]
        metadata.pop('semantic_control',None)
        jev=None;route=None
        try:
            if mode=='controlled':
                jev=JevProvider(usage_path=out/mode/'usage_log.json')
                control=SemanticControl(out/mode/'jev_decisions',provider=jev)
                related=system.related_for_control(content,metadata)
                system._control_related=related
                route=control.route_note(content,metadata,related)
                metadata['semantic_control']=route
                metadata['topic']=route['final_route']['selected_topic']
            try:
                nid=system.add_understanding(content,metadata)
                result={'status':'saved','body_preserved':system.memories[nid].content==content,
                    'original_body_preserved':system.memories[record['id']].content==content,
                    'evolution_status':system.records[nid].get('evolution_status')}
            except ValueError:
                result={'status':'needs_review','body_preserved':None,
                    'original_body_preserved':system.memories[record['id']].content==content}
            summary[mode]={'metrics':metrics(nv,jev),'result':result,
                'route':route['final_route'] if route else None}
            # Separate real-API negative-control check. It is not a real teacher hypothesis.
            if mode=='controlled':
                before=len(jev.attempts)
                hypothesis={'id':'negative_control_not_a_teacher_claim',
                    'statement':'이 자료는 감수분열의 상동염색체 분리를 조건별로 비교하도록 요구한다.',
                    'applicable_context':{'conditions':['제공된 영양소 흡수 페이지만']}}
                validation=control.validate_hypothesis(hypothesis,[{'id':record['id'],
                    'content':content,'provenance':record['provenance'],'interpretation_status':'unreviewed'}])
                summary['negative_control']={'validation':validation,
                    'metrics':metrics(SimpleNamespace(attempts=[]),SimpleNamespace(attempts=jev.attempts[before:])),
                    'meaning':'Deliberately unrelated claim; must not be mistaken for contradiction.'}
        finally:system.close()
        save(out/'benchmark.json',summary)
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true',required=True)
    p.add_argument('--note',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.out.exists():raise ValueError('Use a new output directory to keep comparisons independent of cache.')
    value=run(args.note,args.out)
    print(json.dumps({k:value[k] for k in ('baseline','controlled','negative_control')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
