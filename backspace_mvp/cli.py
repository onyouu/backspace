import argparse
import sys
from pathlib import Path
from jsonschema import ValidationError
from .pipeline import ingest, build, generate_plan, writable


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Backspace Teacher Architecture v0.1 · Teacher Intelligence + 지속 학습계획 (구현 단계 v0.7)')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('extract_materials', help='로컬 텍스트·이미지 OCR 인식 결과 저장. NVIDIA/Jev 호출 없음.')
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--out-dir', type=Path, default=Path('state/perception'))
    p.add_argument('--pages', help='대표 페이지 선택. 예: 1,3,5 (전체 입력은 생략)')
    for name in ('ingest_materials', 'analyze_exam'):
        p = commands.add_parser(name)
        p.add_argument('--input', type=Path, required=True)
        p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
        p.add_argument('--exam-id')
        p.add_argument('--refresh', action='store_true', help='같은 원문의 분석을 새 계약/자료 문맥으로 다시 생성합니다.')
        p.add_argument('--memory-workspace',type=Path,help='A-MEM 이해 노트 먼저 저장; 생략 시 기존 추출 방식')
        if name == 'ingest_materials':
            p.add_argument('--material-type', choices=['ppt', 'worksheet', 'other', 'unspecified'])
        else:
            p.add_argument('--answer-key', type=Path, help='문항 번호와 정답·해설 원문 위치를 연결한 mapping JSON')
    p=commands.add_parser('understand_material',help='원문/OCR 캐시 → 자연어 이해 노트 → A-MEM 저장. Graph 생성 없음.')
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--workspace',type=Path,default=Path('state/memory'))
    p.add_argument('--perception-dir',type=Path,default=Path('state/perception'))
    p.add_argument('--kind',choices=['learning_material','exam'],default='learning_material')
    p.add_argument('--exam-id',default='local_exam')
    p.add_argument('--pages',help='읽은 자료 중 선택 위치: p6,p7 또는 slide2')
    p=commands.add_parser('search_memory',help='A-MEM의 로컬 의미 검색. LLM API 호출 없음.')
    p.add_argument('--workspace',type=Path,default=Path('state/memory'))
    p.add_argument('--query',required=True)
    p.add_argument('--source-type',choices=['learning_material','exam_question'])
    p.add_argument('--topic')
    p.add_argument('--limit',type=int,default=5)
    p=commands.add_parser('review_memory',help='오류 노트를 검색·교사 근거에서 제외. 원래 본문은 보존.')
    p.add_argument('--workspace',type=Path,default=Path('state/memory'))
    p.add_argument('--note-id',required=True)
    p.add_argument('--status',choices=['accepted','rejected','unreviewed'],required=True)
    p.add_argument('--reason',required=True)
    p = commands.add_parser('export_question_graphs', help='문제별 Question Graph 내보내기. API 호출 없음.')
    p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
    p.add_argument('--out-dir', type=Path, default=Path('state/question_graphs'))
    p = commands.add_parser('export_material_graph', help='누적 자료 그래프를 검증하고 내보냅니다. API 호출 없음.')
    p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
    p.add_argument('--out', type=Path, default=Path('state/material_graph.json'))
    p = commands.add_parser('mine_patterns', help='활성 Question Graph의 반복 개념·사고·연결·경로·부분 그래프 집계. API 호출 없음.')
    p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
    p.add_argument('--graphs-dir', type=Path, help='생략하면 dataset 옆 question_graphs')
    p.add_argument('--out', type=Path, help='생략하면 dataset 옆 patterns.json')
    p.add_argument('--exam-id', help='특정 시험만 집계; 분모도 그 시험의 포함 문항으로 제한')
    p.add_argument('--min-support', type=int, default=2)
    p.add_argument('--max-path-edges', type=int, choices=[2, 3], default=3)
    p.add_argument('--max-motif-nodes', type=int, choices=[3, 4], default=4)
    p.add_argument('--max-candidates', type=int, default=50000)
    p = commands.add_parser('build_teacher_hypotheses', help='반복 패턴·자료 근거에서 조건부 가설 생성. 실행 시 NVIDIA API 사용.')
    p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
    p.add_argument('--out', type=Path)
    p.add_argument('--patterns', type=Path)
    p.add_argument('--material-graph', type=Path)
    p.add_argument('--graphs-dir', type=Path)
    p.add_argument('--refresh', action='store_true')
    p.add_argument('--max-hypotheses', type=int, default=4)
    p.add_argument('--max-patterns', type=int, default=12)
    p.add_argument('--max-questions', type=int, default=24)
    p.add_argument('--max-material-items', type=int, default=12)
    p.add_argument('--max-context-chars', type=int, default=48000)
    p = commands.add_parser('score_teacher', help='가설과 개념의 차원을 Jev로 판단. 실행 시 TypeSafe API 사용.')
    p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
    p.add_argument('--out', type=Path)
    p.add_argument('--hypotheses', type=Path)
    p.add_argument('--patterns', type=Path)
    p.add_argument('--material-graph', type=Path)
    p.add_argument('--graphs-dir', type=Path)
    p.add_argument('--teacher-model', type=Path, help='선택: 같은 교사의 기존 v0.6 모델과 일관성 평가')
    p.add_argument('--refresh', action='store_true')
    p.add_argument('--max-concepts', type=int, default=24)
    p.add_argument('--max-hypotheses', type=int, default=8)
    p.add_argument('--max-evidence', type=int, default=24)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--max-context-chars', type=int, default=64000)
    p = commands.add_parser('build_teacher_model')
    p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
    p.add_argument('--out', type=Path)
    p.add_argument('--patterns', type=Path)
    p.add_argument('--material-graph', type=Path)
    p.add_argument('--hypotheses', type=Path)
    p.add_argument('--scores', type=Path)
    p.add_argument('--graphs-dir', type=Path)
    p = commands.add_parser('update_teacher_model', help='Jev 중심 증분 갱신. 새 패턴만 NVIDIA로 생성.')
    p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
    p.add_argument('--max-concepts', type=int, default=4)
    p.add_argument('--manual-rebuild', action='store_true', help='명시적으로 기존 전체 가설 생성 흐름 실행')
    p = commands.add_parser('teacher_feedback', help='사람/실제 시험 피드백을 별도 이력으로 저장')
    p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
    p.add_argument('--hypothesis-id', required=True)
    p.add_argument('--kind', required=True)
    p.add_argument('--reason', required=True)
    p.add_argument('--scope-json', help='범위 수정 시 level/conditions JSON')
    p = commands.add_parser('build_legacy_teacher_report', help='이전 실험용 분석 보고서. v0.6 Teacher Model과 별도.')
    p.add_argument('--state', type=Path, default=Path('state/dataset.json'))
    p.add_argument('--out', type=Path, default=Path('state/legacy_teacher_report.json'))
    p.add_argument('--min-support', type=int, default=2)
    p = commands.add_parser('generate_plan')
    p.add_argument('--model', type=Path, default=Path('state/teacher_model.json'))
    p.add_argument('--materials-state', type=Path, required=True, help='새 시험범위 학습자료의 별도 dataset')
    p.add_argument('--material-graph', type=Path)
    p.add_argument('--out', type=Path)
    p.add_argument('--exam-format', default='서술형')
    p.add_argument('--days', type=int, default=7)
    p.add_argument('--daily-minutes', type=int, default=60)
    p.add_argument('--max-concepts', type=int, default=12)
    p.add_argument('--max-context-chars', type=int, default=64000)
    p.add_argument('--feedback', help='계획 생성 시 반영할 대화/추가 메모. 원문과 처리 이력 저장.')
    p.add_argument('--offline', action='store_true', help='API 없이 기존 동일 개념 중요도와 명시적 템플릿 사용')
    p.add_argument('--refresh', action='store_true', help='Jev·NVIDIA 완료 체크포인트를 사용하지 않고 다시 요청')
    p = commands.add_parser('update_plan', help='진행 상태 또는 대화/추가 데이터 기록. API 호출 없음.')
    p.add_argument('--plan', type=Path, default=Path('state/current_plan.json'))
    p.add_argument('--event-type', required=True, choices=['progress', 'conversation', 'additional_data', 'constraint'])
    p.add_argument('--note', default='')
    p.add_argument('--task-id')
    p.add_argument('--status', choices=['pending', 'in_progress', 'completed'])
    p = commands.add_parser('generate_legacy_plan', help='이전 실험 보고서용 계획. 새 v0.7과 별도.')
    p.add_argument('--model', type=Path, default=Path('state/legacy_teacher_report.json'))
    p.add_argument('--out', type=Path, default=Path('state/plan.json'))
    p.add_argument('--exam-format', default='서술형')
    p.add_argument('--feedback', help='향후 적응 기능을 위한 대화/추가 데이터 메모. 자동 해석하지 않음.')
    p = commands.add_parser('diagnose_exam', help='Separate a short plain answer from structured extraction')
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path('output/exam_diagnosis.json'))
    args = parser.parse_args(argv)
    try:
        if args.command=='understand_material':
            from .pipeline import read_source
            from .understanding import UnderstandingWorkspace
            inputs={}
            source=read_source(args.input,args.kind,args.exam_id if args.kind=='exam' else None,
                perception_dir=args.perception_dir,visual_inputs=inputs)
            with UnderstandingWorkspace(args.workspace) as workspace:
                result=workspace.ingest_source(source,visual_inputs=inputs,
                    locators=args.pages.split(',') if args.pages else None,
                    progress=lambda stage,cached:print(stage+(' · 저장 결과 재사용' if cached else ''),flush=True))
            print(f"이해 노트 {len(result['note_ids'])}개 저장: {args.workspace}")
        elif args.command=='review_memory':
            from .understanding import review_saved_note
            review_saved_note(args.workspace,args.note_id,args.status,args.reason)
            print('노트 검토 상태 저장: '+args.note_id)
        elif args.command=='search_memory':
            from .understanding import search_saved_memory
            import json
            print(json.dumps(search_saved_memory(args.workspace,args.query,k=args.limit,
                source_type=args.source_type,topic=args.topic),ensure_ascii=False,indent=2))
        elif args.command == 'extract_materials':
            from .perception import extract_document
            pages = [int(p) for p in args.pages.split(',')] if args.pages else None
            result, destination = extract_document(args.input, args.out_dir,
                page_range=pages, progress=lambda loc,n: print(f'저장: {loc}', flush=True))
            print(f"인식 저장: {destination}; {result['coverage']}")
        elif args.command == 'diagnose_exam':
            from .llm_provider import create_provider
            from .pipeline import read_source, save
            source = read_source(args.input, 'exam', 'diagnosis')
            if len(source['excerpts']) != 1 or len(source['excerpts'][0]['text']) > 4000:
                raise ValueError('진단은 한 페이지의 짧은 텍스트 문항으로 실행하세요.')
            provider = create_provider(task='exam')
            answer = provider.complete_text('다음 생명과학 문제에 간결한 정답을 쓰세요.\n' + source['excerpts'][0]['text'])
            save(args.out, {'question': source['excerpts'][0]['text'], 'answer': answer,
                           'model': provider.last_model, 'diagnostic_log': str(provider.log_path)})
            print(answer)
            print(f'진단 저장: {args.out}')
        elif args.command in ('ingest_materials', 'analyze_exam'):
            result = ingest(args.state, args.input,
                'learning_material' if args.command == 'ingest_materials' else 'exam', args.exam_id,
                refresh=args.refresh, material_type=getattr(args, 'material_type', None),
                answer_key=getattr(args, 'answer_key', None),memory_workspace=args.memory_workspace)
            print(f"저장: {args.state}; 개념 {len(result['concepts'])}, 문항 {len(result['questions'])}")
            if args.command == 'ingest_materials':
                print(f'누적 자료 그래프: {args.state.parent / "material_graph.json"}')
            else:
                print(f'문제별 그래프: {args.state.parent / "question_graphs"}')
        elif args.command == 'export_question_graphs':
            from .question_graphs import export_question_graphs
            from .model import read_json
            if args.state.resolve().parent == args.out_dir.resolve():
                raise ValueError('Question Graph 출력은 dataset과 별도 폴더를 사용하세요.')
            result = export_question_graphs(read_json(args.state), args.out_dir)
            print(f"저장: {args.out_dir}; Question Graph {len(result['questions'])}개, 재분석 필요 {len(result['needs_reanalysis'])}개")
        elif args.command == 'export_material_graph':
            from .materials import export_material_graph
            from .model import read_json
            if args.state.resolve() == args.out.resolve():
                raise ValueError('자료 그래프와 dataset은 서로 다른 경로에 저장하세요.')
            result = export_material_graph(read_json(args.state), args.out)
            print(f"저장: {args.out}; revision {result['revision']}, 개념 {len(result['concepts'])}, 관계 {len(result['relations'])}")
        elif args.command == 'mine_patterns':
            from .patterns import build_patterns
            result = build_patterns(args.state, args.out, args.graphs_dir, args.exam_id,
                min_support=args.min_support, max_path_edges=args.max_path_edges,
                max_motif_nodes=args.max_motif_nodes, max_candidates=args.max_candidates)
            destination = args.out if args.out else args.state.parent / 'patterns.json'
            print(f"저장: {destination}; 문항 {result['counts']['questions']}, revision {result['revision']}")
            print('반복 패턴: ' + ', '.join(f"{k} {v}" for k, v in result['counts']['repeated_patterns'].items()))
        elif args.command == 'build_teacher_hypotheses':
            from .hypotheses import build_teacher_hypotheses
            result = build_teacher_hypotheses(args.state, args.out, args.patterns, args.material_graph,
                args.graphs_dir, refresh=args.refresh, max_hypotheses=args.max_hypotheses,
                max_patterns=args.max_patterns, max_questions=args.max_questions,
                max_material_items=args.max_material_items, max_context_chars=args.max_context_chars)
            destination = args.out if args.out else args.state.parent / 'teacher_hypotheses.json'
            print(f"저장: {destination}; 가설 {len(result['hypotheses'])}, revision {result['revision']}, {result['generation']['status']}")
        elif args.command == 'score_teacher':
            from .scoring import build_teacher_scores
            result = build_teacher_scores(args.state, args.out, args.hypotheses, args.patterns,
                args.material_graph, args.graphs_dir, args.teacher_model, refresh=args.refresh,
                max_concepts=args.max_concepts, max_hypotheses=args.max_hypotheses,
                max_evidence=args.max_evidence, batch_size=args.batch_size, max_context_chars=args.max_context_chars)
            destination = args.out if args.out else args.state.parent / 'teacher_scores.json'
            print(f"저장: {destination}; 개념 {len(result['concept_scores'])}, 가설 {len(result['hypothesis_scores'])}, revision {result['revision']}")
        elif args.command == 'build_teacher_model':
            from .teacher_model import build_teacher_model
            result = build_teacher_model(args.state, args.out, args.patterns, args.material_graph,
                args.hypotheses, args.scores, args.graphs_dir)
            destination = args.out if args.out else args.state.parent / 'teacher_model.json'
            print(f"저장: {destination}; 개념 {result['counts']['concepts']}, 가설 {result['counts']['hypotheses']}, revision {result['revision']}")
        elif args.command == 'build_legacy_teacher_report':
            result = build(args.state, args.out, args.min_support)
            print(f"저장: {args.out}; 문항 {result['counts']['questions']}")
        elif args.command == 'update_teacher_model':
            from .teacher_incremental import update_teacher_model
            result = update_teacher_model(args.state, max_concepts=args.max_concepts, manual_rebuild=args.manual_rebuild)
            print(f"교사 모델 저장: {args.state.parent / 'teacher_model.json'}; 추가 확인 {result.get('incremental', {}).get('pending_count', 0)}건")
        elif args.command == 'teacher_feedback':
            import json
            from .model import read_json
            from .teacher_update import TeacherModelUpdateEngine
            scope = read_json(args.state)['scope']
            engine = TeacherModelUpdateEngine(args.state.parent / 'teacher_model', scope=scope)
            result = engine.record_feedback(args.hypothesis_id, args.kind, reason=args.reason,
                scope=json.loads(args.scope_json) if args.scope_json else None)
            print(f"피드백 저장: {result['id']}; 다음 교사 모델 갱신에 반영됩니다.")
        elif args.command == 'generate_plan':
            from .study_plan import generate_study_plan
            result = generate_study_plan(args.model, args.materials_state, args.out, args.material_graph,
                exam_format=args.exam_format, days=args.days, daily_minutes=args.daily_minutes,
                max_concepts=args.max_concepts, max_context_chars=args.max_context_chars,
                feedback=args.feedback, offline=args.offline, refresh=args.refresh)
            destination = args.out if args.out else args.model.parent / 'current_plan.json'
            print(f"저장: {destination}; 과제 {len(result['tasks'])}, revision {result['revision']}, 시간 초과 {result['budget']['overflow_minutes']}분")
        elif args.command == 'update_plan':
            from .study_plan import update_study_plan
            result = update_study_plan(args.plan, args.event_type, args.note, args.task_id, args.status)
            print(f"저장: {args.plan}; revision {result['revision']}, 수정 검토 필요 {result['needs_revision']}")
        else:
            result = generate_plan(args.model, args.out, args.exam_format, args.feedback)
            print(f"저장: {args.out}; 계획 revision {result['revision']}, 활동 {len(result['tasks'])}")
    except (ValueError, OSError, ValidationError, KeyError) as exc:
        message = exc.message if isinstance(exc, ValidationError) else str(exc)
        print(f'실패: {message}', file=sys.stderr)
        raise SystemExit(2) from None
