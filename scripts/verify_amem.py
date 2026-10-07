"""Bounded real-data A-MEM validation. --live explicitly enables NVIDIA calls."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--file-id',default='cf0b223f35753aabf66e5e36')
    parser.add_argument('--locator',default='p7')
    parser.add_argument('--out',type=Path,default=ROOT/'output/amem_validation')
    parser.add_argument('--project-graph',action='store_true')
    args=parser.parse_args()
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if not args.live:parser.error('--live를 명시하면 선택한 한 페이지의 NVIDIA 노트·메타데이터를 생성합니다.')
    from backspace_mvp.model import read_json
    from backspace_mvp.pipeline import save,empty_dataset,digest
    from backspace_mvp.perception import source_from_document
    from backspace_mvp.understanding import UnderstandingWorkspace,list_saved_notes
    from backspace_mvp.nvidia import NvidiaProvider
    base=ROOT/'state/web/workspace'
    row=next(r for r in read_json(base/'files.json') if r['id']==args.file_id)
    original=base/'uploads'/(row['id']+row['suffix'])
    normalized=base/row['perception_manifest']
    if not normalized.exists():raise ValueError('먼저 저장된 OCR 결과가 필요합니다. 검증에서는 OCR을 실행하지 않습니다.')
    before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in (original,normalized)]
    document=read_json(normalized)
    from backspace_mvp.visual import attach_reports
    source=attach_reports(source_from_document(original,document,'learning_material'),document,normalized)
    source['title']=row['name']
    provider=NvidiaProvider(env_file=ROOT/'.env',task='understanding',timeout=60,usage_path=args.out/'usage_log.json')
    provider.fallback=provider.model;provider.preferred_model=provider.model;provider.max_tokens=1536
    with UnderstandingWorkspace(args.out/'memory',provider=provider) as workspace:
        manifest=workspace.ingest_source(source,locators=[args.locator],
            progress=lambda stage,cached:print(stage+' '+('cache' if cached else 'new'),flush=True))
        notes=list_saved_notes(args.out/'memory')
        first=notes['notes'][0]
        search=workspace.search('영양소 검출과 소화제 실험',k=3)
        replay=workspace.ingest_source(source,locators=[args.locator])
        assert replay==manifest
    verification={'source':row['name'],'locator':args.locator,'coverage':manifest['coverage'],
        'notes':len(manifest['note_ids']),'search_ids':[n['id'] for n in search],
        'notes_provider_log':str(provider.log_path),'upstream':'agiresearch/A-mem',
        'calls':len(provider.attempts),'original_and_ocr_unchanged':before==[
            hashlib.sha256(p.read_bytes()).hexdigest() for p in (original,normalized)],
        'limitations':['실제 자료 한 페이지 검증이며 전체 문서·교사 모델의 정확도 검증은 아니다.',
            'Understanding Note는 원문에 대한 AI 해석이며 사람의 검토가 필요하다.']}
    if args.project_graph:
        from backspace_mvp.staged import StagedExtractor
        graph=NvidiaProvider(env_file=ROOT/'.env',task='learning_material',timeout=60,usage_path=args.out/'usage_log.json')
        graph.fallback=graph.model;graph.preferred_model=graph.model;graph.max_tokens=3072
        ex=StagedExtractor(graph,empty_dataset(),source,args.out/'graph_checkpoints',understanding_units=manifest['units'])
        page=next(ex.pages())
        try:
            relations=ex.material(page)
            save(args.out/'graph_projection.json',{'locator':args.locator,'concepts':ex.concepts,
                'relations':relations,'observations':ex.material_observations,'primary_note_id':first['id']})
            verification['graph_projection']={'status':'passed','concepts':len(ex.concepts),'relations':len(relations)}
        except ValueError as exc:
            verification['graph_projection']={'status':'failed','error':str(exc),'notes_preserved':True}
        verification['graph_log']=str(graph.log_path)
        verification['graph_calls']=len(graph.attempts)
        if hasattr(ex,'_review_provider'):
            verification['review_calls']=len(ex._review_provider.attempts)
            verification['review_log']=str(ex._review_provider.log_path)
    save(args.out/'verification.json',verification)
    content='# 실제 자료 이해 노트 — '+row['name']+' · '+args.locator+'\n\n'+first['content']
    content+='\n\n## 검증 범위\n\n'+json.dumps(verification,ensure_ascii=False,indent=2)+'\n'
    from backspace_mvp.understanding import write_text
    write_text(args.out/'preview.md',content)
    print(json.dumps(verification,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
