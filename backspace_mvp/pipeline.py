import copy
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from .analysis import analyze
from .model import SCHEMA, merge, read_json, validate, validate_report


def writable(path):
    path = Path(path).resolve()
    if any(p.casefold() in ('sources', '학습자료', '시험지') for p in path.parts):
        raise ValueError('참조 폴더에는 저장할 수 없습니다.')
    return path


def save(path, value):
    path = writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def empty_dataset():
    return {'schema_version': '1.1', 'reasoning_codes': read_json(Path(__file__).parent / 'schemas/reasoning_codes.json'), 'scope': {'teacher_id': 'local', 'subject': '생명과학',
            'label': '로컬 교사 자료', 'teacher_identity_verified': False},
            'notes': ['출제 의도는 관찰에 기반한 분석 가설입니다.'],
            **{k: [] for k in ('sources', 'concepts', 'material_relations', 'questions')}}


def read_source(path, kind, exam_id=None, material_type=None, *, perception_dir=None, progress=None, reader=None, visual_inputs=None):
    from .perception import extract_document, source_from_document
    folder = Path(perception_dir) if perception_dir else Path('state/perception')
    document, manifest = extract_document(path, folder, reader=reader, progress=progress)
    from .visual import attach_reports
    return attach_reports(source_from_document(path, document, kind, exam_id, material_type),
                          document, manifest, visual_inputs)


def ingest(state, input_path, kind, exam_id=None, provider=None, refresh=False, material_type=None, answer_key=None, source_title=None, perception_dir=None, progress=None, analysis_progress=None, memory_workspace=None, prepared_source=None, prepared_manifest=None, prepared_visual_inputs=None):
    writable(state)
    if kind == 'learning_material' and Path(state).resolve() == (Path(state).parent / 'material_graph.json').resolve():
        raise ValueError('dataset 상태 경로는 material_graph.json과 달라야 합니다.')
    if Path(state).resolve() == Path(input_path).resolve():
        raise ValueError('입력 파일을 상태 저장소로 덮어쓸 수 없습니다.')
    base = validate(read_json(state)) if Path(state).exists() else empty_dataset()
    if Path(input_path).suffix.lower() == '.json':
        if answer_key:
            raise ValueError('--answer-key는 원문 시험 입력에서 사용하세요. 구조화 JSON은 연결된 해설을 포함해야 합니다.')
        if refresh:
            raise ValueError('--refresh는 원문 PDF/PPTX/TXT/MD 입력에서만 지원합니다.')
        addition = validate(read_json(input_path))
        expected = 'learning_material' if kind == 'learning_material' else 'exam'
        addition = copy.deepcopy(addition)
        addition['sources'] = [s for s in addition['sources'] if kind == 'exam' or s['kind'] == expected]
        if kind == 'learning_material':
            addition['questions'] = []
        else:
            addition['material_relations'] = []
        allowed = {s['id'] for s in addition['sources']}
        if 'material_observations' in addition:
            addition['material_observations'] = [o for o in addition['material_observations']
                if all(e['source_id'] in allowed for e in o['evidence'])]
        if not Path(state).exists():
            base['scope'] = addition['scope']
    else:
        visual_inputs = {}
        source = copy.deepcopy(prepared_source) if prepared_source is not None else read_source(input_path, kind, exam_id, material_type,
            perception_dir=perception_dir or Path(state).parent / 'perception', progress=progress, visual_inputs=visual_inputs)
        if prepared_visual_inputs is not None:visual_inputs=prepared_visual_inputs
        if not source['excerpts']:
            raise ValueError('인식 결과는 저장했습니다. 분석 가능한 텍스트가 없습니다. 인식 결과에서 확인 대기 영역을 검토하세요.')
        if source_title:
            source['title'] = str(source_title)
        existing_source = any(s['id'] == source['id'] for s in base['sources'])
        answer_sources, answer_mapping = [], {}
        if kind == 'exam':
            from .answer_keys import load_answer_keys, saved_answer_keys
            previous = next((s for s in base['sources'] if s['id'] == source['id']), None)
            if answer_key:
                answer_sources, answer_mapping, identity = load_answer_keys(answer_key, exam_id)
                source['answer_key_manifest_hash'] = identity
                source['answer_key_mapping'] = [{'exam_locator': loc, 'question_number': number,
                    'block_ids': [b['block_id'] for b in blocks]}
                    for (loc, number), blocks in sorted(answer_mapping.items())]
                if previous and previous.get('answer_key_manifest_hash') != identity and not refresh:
                    raise ValueError('정답·해설이 추가/변경됐습니다. --refresh로 문항을 재분석하세요.')
            elif previous:
                answer_sources, answer_mapping = saved_answer_keys(base, source['id'])
                if previous.get('answer_key_manifest_hash'):
                    source['answer_key_manifest_hash'] = previous['answer_key_manifest_hash']
                    source['answer_key_mapping'] = previous.get('answer_key_mapping', [])
        if existing_source and kind == 'learning_material' and material_type is None:
            previous_type = next(s for s in base['sources'] if s['id'] == source['id']).get('material_type')
            if previous_type:
                source['material_type'] = previous_type
        if existing_source and not refresh:
            previous = next(s for s in base['sources'] if s['id'] == source['id'])
            if previous.get('visual_context') != source.get('visual_context'):
                raise ValueError('그림 분석이 변경됐습니다. --refresh 또는 웹 재분석으로 반영하세요.')
            if previous.get('perception', {}).get('content_hash') != source['perception']['content_hash']:
                raise ValueError('인식 결과가 추가/수정됐습니다. --refresh 또는 웹 재분석으로 최신 텍스트를 반영하세요.')
            if material_type and next(s for s in base['sources'] if s['id'] == source['id']).get('material_type') != material_type:
                raise ValueError('자료 유형 변경은 --refresh로 명시하세요.')
            if memory_workspace is not None:
                from .understanding import UnderstandingWorkspace
                from .nvidia import NvidiaProvider
                notes_provider=(NvidiaProvider(task='understanding',usage_path=Path(state).parent/'usage_log.json')
                    if provider is None else NvidiaProvider(env_file=provider.env_file,task='understanding',usage_path=provider.usage_path)
                    if isinstance(provider,NvidiaProvider) else provider)
                with UnderstandingWorkspace(memory_workspace,provider=notes_provider,subject=base['scope']['subject']) as workspace:
                    workspace.ingest_source(source,visual_inputs=visual_inputs,progress=analysis_progress)
            if kind == 'learning_material':
                from .materials import export_material_graph
                export_material_graph(base, Path(state).parent / 'material_graph.json')
            elif kind == 'exam':
                from .question_graphs import export_question_graphs
                export_question_graphs(base, Path(state).parent / 'question_graphs')
            return base
        if provider is None:
            from .nvidia import NvidiaProvider
            provider = NvidiaProvider(task=kind, usage_path=Path(state).parent / 'usage_log.json')
        understanding_units=prepared_manifest['units'] if prepared_manifest is not None else None
        if memory_workspace is not None and prepared_manifest is None:
            from .understanding import UnderstandingWorkspace
            from .nvidia import NvidiaProvider
            note_provider=(NvidiaProvider(env_file=provider.env_file,task='understanding',
                usage_path=provider.usage_path) if isinstance(provider,NvidiaProvider) else provider)
            with UnderstandingWorkspace(memory_workspace,provider=note_provider,subject=base['scope']['subject']) as workspace:
                note_manifest=workspace.ingest_source(source,visual_inputs=visual_inputs,progress=analysis_progress)
                if any(read_json(Path(memory_workspace)/'notes'/(nid+'.json')).get('review_status')=='rejected' for nid in note_manifest['note_ids']):
                    raise ValueError('오류로 표시된 이해 노트가 있습니다. 원문/OCR을 수정한 뒤 다시 분석하세요. 기존 상태는 보존됩니다.')
            understanding_units=note_manifest['units']
            if not note_manifest['coverage']['complete']:
                raise ValueError('자료 일부의 이해 노트만 저장했습니다. 미완료 구간은 재개할 수 있습니다.')
        from .staged import StagedExtractor
        addition = StagedExtractor(provider, base, source, Path(state).parent / 'checkpoints',
                                   answer_sources, answer_mapping, progress=analysis_progress, visual_inputs=visual_inputs,
                                   understanding_units=understanding_units).extract()
        if existing_source and refresh:
            # Commit replacement only after every new stage has succeeded.
            base = copy.deepcopy(base)
            base['material_relations'] = [r for r in base['material_relations']
                if not any(e['source_id'] == source['id'] for e in r['evidence'])]
            base['questions'] = [q for q in base['questions']
                if not any(e['source_id'] == source['id'] for e in q['evidence'])]
            if 'material_observations' in base:
                base['material_observations'] = [o for o in base['material_observations']
                    if not any(e['source_id'] == source['id'] for e in o['evidence'])]
            # Explicit refresh may update a source's declared material type.
            base['sources'] = [s for s in base['sources'] if s['id'] != source['id']]
    result = merge(base, addition)
    if Path(input_path).suffix.lower() != '.json':
        for note in addition['notes']:
            if note not in result['notes']:
                result['notes'].append(note)
        actual_model = getattr(provider, 'last_model', None)
        if actual_model:
            result['notes'].append(f"분석 모델: {source['id']} → {actual_model}")
    save(state, result)
    if kind == 'learning_material':
        from .materials import export_material_graph
        export_material_graph(result, Path(state).parent / 'material_graph.json')
    elif kind == 'exam':
        from .question_graphs import export_question_graphs
        export_question_graphs(result, Path(state).parent / 'question_graphs')
    return result


def build(state, out, min_support=2):
    if Path(out).exists() and read_json(out).get('implementation_milestone') == '0.6':
        raise ValueError('기존 v0.6 Teacher Model을 실험용 보고서로 덮어쓸 수 없습니다. 다른 출력 경로를 사용하세요.')
    if Path(state).resolve() == Path(out).resolve():
        raise ValueError('teacher model은 dataset과 다른 경로에 저장하세요.')
    data = validate(read_json(state))
    report = validate_report(analyze(data, min_support)[0])
    report['dataset_hash'] = digest(data)
    save(out, report)
    return report


def generate_plan(model_path, out, exam_format='서술형', feedback=None):
    if Path(out).exists() and read_json(out).get('implementation_milestone') == '0.7':
        raise ValueError('기존 v0.7 계획을 실험용 계획으로 덮어쓸 수 없습니다. 다른 출력 경로를 사용하세요.')
    if Path(model_path).resolve() == Path(out).resolve():
        raise ValueError('plan은 teacher model과 다른 경로에 저장하세요.')
    report = read_json(model_path)
    fingerprint = report.pop('dataset_hash')
    validate_report(report)
    if not report['questions']:
        raise ValueError('시험 문항이 없어 학습계획을 만들 수 없습니다.')
    old = read_json(out) if Path(out).exists() else None
    schema = read_json(Path(__file__).parent / 'schemas/plan.schema.json')
    if old:
        Draft202012Validator(schema).validate(old)
        if old['teacher_scope'] != report['scope']:
            raise ValueError('다른 교사 범위의 계획을 덮어쓸 수 없습니다.')
    from .planning import make_tasks
    tasks = make_tasks(report, exam_format, old['tasks'] if old else [])
    now = datetime.now(timezone.utc).isoformat()
    plan = {'schema_version': '1.1', 'student_observation': 'not_observed', 'teacher_scope': report['scope'],
            'revision': old['revision'] + 1 if old else 1,
            'dataset_hash': fingerprint, 'exam_format': exam_format, 'updated_at': now,
            'tasks': tasks, 'events': old['events'][:] if old else [],
            'assumptions': ['학생 개인 데이터 없음', '빈도는 관찰이며 교사 성향의 확정이 아님',
                            '그림 및 표 의미는 텍스트 추출만으로 검증하지 않음']}
    plan['events'].append({'at': now, 'type': 'revision', 'text': feedback or 'Teacher Model 기반 계획 생성'})
    Draft202012Validator(schema).validate(plan)
    if old:
        archive = Path(out).parent / 'plan_history' / (Path(out).stem + '-r' + str(old['revision']) + '-' + digest(old)[:16] + '.json')
        save(archive, old)
    save(out, plan)
    return plan
