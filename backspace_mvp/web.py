"""Loopback-only web adapter for two distinct input corpora and background jobs.

No credentials, arbitrary files or paths are exposed. Uses the existing pipeline.
This is a single-user local prototype, not a public production server.
"""
import argparse
import copy
import hashlib
import json
import mimetypes
import os
import io
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from dotenv import dotenv_values
from jsonschema import ValidationError
from .model import read_json
from .pipeline import digest, empty_dataset, ingest, save
from .materials import export_material_graph
from .question_graphs import export_question_graphs
from .patterns import build_patterns
from .hypotheses import build_teacher_hypotheses
from .scoring import build_teacher_scores
from .teacher_model import build_teacher_model
from .study_plan import generate_study_plan, update_study_plan

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / 'web_static'
MAX_FILE = 100 * 1024 * 1024
KINDS = {'material': 'learning_material', 'exam': 'exam'}
ARTIFACTS = {'material': 'material_graph.json', 'patterns': 'patterns.json',
             'model': 'teacher_model.json', 'hypotheses': 'teacher_hypotheses.json'}


def backend_revision():
    files=('web.py','web_pipeline.py','staged.py','grounded.py','nvidia.py','stage_state.py','understanding.py',
           'teacher_update.py','teacher_incremental.py','teacher_note_evidence.py','teacher_questions.py',
           'semantic_control.py')
    return hashlib.sha256(b''.join((Path(__file__).parent/name).read_bytes() for name in files)).hexdigest()[:16]


LOADED_BACKEND_REVISION=backend_revision()


def now():
    return datetime.now(timezone.utc).isoformat()


class WebStore:
    def __init__(self, root=ROOT, storage=None):
        self.root = Path(root).resolve()
        self.storage = Path(storage).resolve() if storage else self.root / 'state/web'
        self.workspace = self.storage / 'workspace'
        self.mutex = threading.RLock()
        self.active = None
        self.jobs = {}
        self.secret_values = {v for k, v in dotenv_values(self.root / '.env').items()
                              if k.endswith('API_KEY') and v}
        self.secret_values.update(v for k, v in os.environ.items() if k.endswith('API_KEY') and v)
        self.prepare_demo()
        # Interrupted jobs do not restart or spend tokens on server restart.
        for path in (self.storage / 'jobs').glob('*.json'):
            value = read_json(path)
            if value['status'] in ('queued', 'running'):
                value.update(status='interrupted', error='서버가 종료돼 중단됐습니다. 완료된 단계는 보존됩니다.')
                save(path, value)
            self.jobs[value['id']] = value

    def clean(self, value):
        if isinstance(value, dict):
            return {k: self.clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for secret in self.secret_values:
                value = value.replace(secret, '[REDACTED]')
        return value

    def prepare_demo(self):
        demo = self.storage / 'demo'
        target = demo / 'teacher'
        state = target / 'dataset.json'
        verified = self.root / 'state/integration_v07/live'
        if not state.exists():
            original = verified / 'dataset.json'
            data = read_json(original if original.exists() else self.root / 'data/question_graph_v02/offline_fixture.json')
            save(state, data)
            export_material_graph(data, target / 'material_graph.json')
            export_question_graphs(data, target / 'question_graphs')
            build_patterns(state)
            for name in ('teacher_model.json', 'teacher_hypotheses.json'):
                if (verified / name).exists():
                    save(target / name, read_json(verified / name))
        # Example corpus is ingested separately as this exam's range; never merged into teacher.
        scope = demo / 'scope/dataset.json'
        if not scope.exists():
            ingest(scope, state, 'learning_material')
        # Rebuild deterministic demo views after projection/schema changes.
        # Existing examples can have valid old graphs that no longer match their dataset.
        export_material_graph(read_json(state), target / 'material_graph.json')
        export_material_graph(read_json(scope), scope.parent / 'material_graph.json')
        if (target / 'teacher_model.json').exists() and not (demo / 'current_plan.json').exists():
            generate_study_plan(target / 'teacher_model.json', scope, out=demo / 'current_plan.json',
                                offline=True, max_concepts=5)

    def base(self, mode):
        if mode not in ('demo', 'workspace'):
            raise ValueError('알 수 없는 작업공간입니다.')
        return self.storage / mode

    def files(self):
        path = self.workspace / 'files.json'
        return read_json(path) if path.exists() else []

    def upload(self, body, filename, target, kind, exam_id='', material_type='unspecified'):
        return self.upload_stream(io.BytesIO(body),len(body),filename,target,kind,exam_id,material_type)

    def upload_stream(self, stream, size, filename, target, kind, exam_id='', material_type='unspecified'):
        if target not in ('teacher', 'scope') or kind not in KINDS:
            raise ValueError('자료 목적과 종류를 선택하세요.')
        if target == 'scope' and kind != 'material':
            raise ValueError('시험범위 입력에는 학습자료를 올려주세요.')
        if kind == 'exam' and not re.fullmatch(r'[\w-]{1,80}', exam_id):
            raise ValueError('시험 이름은 문자·숫자·밑줄·하이픈으로 1~80자 입력하세요.')
        if material_type not in ('ppt', 'worksheet', 'other', 'unspecified'):
            raise ValueError('알 수 없는 자료 종류입니다.')
        filename = Path(filename.replace('\\', '/')).name
        suffix = Path(filename).suffix.lower()
        if suffix not in ('.pdf', '.pptx', '.txt', '.md', '.json','.png','.jpg','.jpeg') or not 0 < size <= MAX_FILE:
            raise ValueError('PDF/PPTX/PNG/JPG/TXT/MD/JSON 파일을 100MB 이하로 올려주세요.')
        with self.mutex:
            if self.active:
                raise ValueError('현재 작업이 끝난 뒤 자료를 추가하세요.')
        folder=self.workspace/'uploads'
        folder.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(dir=folder,suffix='.upload')
        try:
            h=hashlib.sha256()
            with os.fdopen(fd,'wb') as out:
                remaining=size
                while remaining:
                    chunk=stream.read(min(1024*1024,remaining))
                    if not chunk:
                        raise ValueError('파일 전송이 완료되지 않았습니다.')
                    out.write(chunk); h.update(chunk); remaining-=len(chunk)
                out.flush(); os.fsync(out.fileno())
            sha=h.hexdigest()
            fid=digest([sha,target,kind,exam_id,material_type])[:24]
            with self.mutex:
                if self.active:
                    raise ValueError('현재 작업이 끝난 뒤 자료를 추가하세요.')
                files=self.files()
                if any(f['id']==fid for f in files):
                    return next(f for f in files if f['id']==fid)
                os.replace(name,folder/(fid+suffix))
                row={'id':fid,'name':filename,'suffix':suffix,'sha256':sha,'bytes':size,
                     'target':target,'kind':kind,'exam_id':exam_id,'material_type':material_type,
                     'status':'pending','at':now()}
                files.append(row); save(self.workspace/'files.json',files)
                return row
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def _file(self, fid):
        row=next((f for f in self.files() if f['id']==fid),None)
        if row is None:
            raise ValueError('자료를 찾을 수 없습니다.')
        return row

    def perception_path(self, fid):
        row=self._file(fid)
        if not row.get('perception_manifest'):
            raise ValueError('먼저 「자료 읽기」를 실행하세요.')
        path=(self.workspace/row['perception_manifest']).resolve()
        if (self.workspace/'perception').resolve() not in path.parents:
            raise ValueError('잘못된 인식 결과 위치입니다.')
        return path

    def perception(self, fid):
        from .perception import validate
        return self.clean(validate(read_json(self.perception_path(fid))))

    def review(self, payload):
        from .perception import review_document
        with self.mutex:
            if self.active:
                raise ValueError('자료 읽기/분석이 끝난 후 수정하세요.')
            fid=payload.get('file_id')
            doc=review_document(self.perception_path(fid),payload.get('revision'),
                payload.get('block_id'),payload.get('text'),payload.get('locator'),payload.get('acknowledge_visual',False))
            files=self.files(); row=next(f for f in files if f['id']==fid)
            row.update(status='pending',read_status=doc['status'],coverage=doc['coverage'],
                       perception_hash=doc['content_hash'])
            save(self.workspace/'files.json',files)
            return self.clean(doc)

    def _read_file(self, row, progress):
        from .perception import extract_document
        path=self.workspace/'uploads'/(row['id']+row['suffix'])
        try:
            doc,manifest=extract_document(path,self.workspace/'perception',progress=progress)
        except Exception as exc:
            files = self.files()
            for item in files:
                if item['id'] == row['id']:
                    item['read_error'] = self.clean(str(exc))
            save(self.workspace/'files.json', files)
            raise
        row.pop('read_error', None)
        row.update(perception_manifest=str(manifest.relative_to(self.workspace)),
                   read_status=doc['status'],coverage=doc['coverage'],perception_hash=doc['content_hash'])
        files=self.files()
        for f in files:
            if f['id']==row['id']:
                f.pop('read_error', None)
                f.update(row)
        save(self.workspace/'files.json',files)
        return doc

    def data(self, mode):
        base = self.base(mode)
        state = base / 'teacher/dataset.json'
        data = read_json(state) if state.exists() else empty_dataset()
        scope_state = base / 'scope/dataset.json'
        scope_data = read_json(scope_state) if scope_state.exists() else empty_dataset()
        result = {'mode': mode, 'dataset': data, 'scope_dataset': scope_data,
                  'scope_material': None, 'plan': None, 'files': self.files() if mode == 'workspace' else [],
                  'model_stale': False, 'plan_stale': False,
                  'job': copy.deepcopy(self.jobs.get(self.active)) if self.active else None}
        for key, filename in ARTIFACTS.items():
            path = base / 'teacher' / filename
            result[key] = read_json(path) if path.exists() else None
        if result['model']:
            result['model_stale'] = result['model']['inputs']['dataset_hash'] != digest(data)
        if mode=='workspace':
            for row in result['files']:
                dataset=data if row['target']=='teacher' else scope_data
                source=next((s for s in dataset['sources'] if s['sha256']==row['sha256'] and s['kind']==KINDS[row['kind']]
                    and (row['kind']!='exam' or s.get('exam_id')==row['exam_id'])),None)
                row['analysis_stale']=bool(source and row.get('perception_hash') and source.get('perception',{}).get('content_hash')!=row['perception_hash'])
            result['model_stale'] |= bool(result['model']) and any(f['target']=='teacher' and
                (f.get('analysis_stale') or f['status']=='pending') for f in result['files'])
        path = base / 'scope/material_graph.json'
        if path.exists():
            result['scope_material'] = read_json(path)
        path = base / 'current_plan.json'
        if path.exists():
            result['plan'] = read_json(path)
            result['plan_stale'] = (not result['model'] or result['model_stale'] or
                result['plan']['inputs']['teacher_model_hash'] != result['model']['content_hash'] or
                result['plan']['inputs']['materials_dataset_hash'] != digest(scope_data) or
                any(f['target']=='scope' and (f.get('analysis_stale') or f['status']=='pending') for f in result['files']))
        result['question_graphs'] = []
        if mode=='workspace':
            from .stage_state import StageLedger
            result['pipeline']={}
            for target in ('teacher','scope'):
                current={r.get('pipeline_source_id',r['id']):r.get('pipeline_input_hash',r['sha256'])
                    for r in result['files'] if r['target']==target}
                ids=set(current)|{'_'+target,'_planning'}
                ds=base/target/'dataset.json'
                if ds.exists():current['_'+target]=digest(read_json(ds))
                snapshot=StageLedger(base/target/'pipeline_state').snapshot(source_ids=ids,current_hashes=current)
                result['pipeline'][target]=snapshot
                for row in result['files']:
                    if row['target']==target:
                        row['stage_tasks']=[t for t in snapshot['tasks'] if t['source_id']==row.get('pipeline_source_id',row['id'])]
        folder = base / 'teacher/question_graphs'
        if (folder / 'index.json').exists():
            for entry in read_json(folder / 'index.json')['questions']:
                # The index is generated internally; nevertheless do not follow arbitrary paths.
                file = folder / Path(entry['file']).name
                result['question_graphs'].append(read_json(file))
        # Hide document filesystem paths in browsing data. Exported model/plan
        # preserve their canonical fields and content hashes.
        for dataset in (result['dataset'], result['scope_dataset']):
            for source in dataset['sources']:
                source.pop('path', None)
        return self.clean(result)

    def start(self, action, options):
        if LOADED_BACKEND_REVISION!=backend_revision():
            raise ValueError('서버 업데이트 적용이 필요합니다. 현재 작업이 끝난 뒤 업데이트된 실행 주소로 접속하세요.')
        if action not in ('read', 'understand', 'visual', 'structure', 'teacher', 'scope', 'plan','resume'):
            raise ValueError('알 수 없는 작업입니다.')
        mode = options.get('mode', 'workspace')
        if mode == 'demo' and action != 'plan':
            raise ValueError('예시 자료는 보존됩니다. 내 자료 작업공간에서 실행하세요.')
        self.base(mode)
        if action == 'visual':
            from .visual import _locator
            self.perception_path(options.get('file_id'))
            _locator(options.get('locator'))
        if action in ('read','understand','resume') and options.get('target','teacher') not in ('teacher','scope'):
            raise ValueError('알 수 없는 자료 목적입니다.')
        if type(options.get('manual_rebuild',False)) is not bool or type(options.get('offline',True)) is not bool:
            raise ValueError('작업 설정을 확인하세요.')
        if action=='resume' and (not isinstance(options.get('task_ids',[]),list) or
                any(not isinstance(t,str) or not re.fullmatch('[0-9a-f]{64}',t) for t in options.get('task_ids',[]))):
            raise ValueError('재개할 작업 ID를 확인하세요.')
        days, minutes = options.get('days', 7), options.get('daily_minutes', 60)
        concept_limit = options.get('max_concepts', 4)
        if (type(days) is not int or type(minutes) is not int or
                not 1 <= days <= 90 or not 5 <= minutes <= 480):
            raise ValueError('학습 기간 1~90일, 하루 5~480분을 입력하세요.')
        if type(concept_limit) is not int or not 1 <= concept_limit <= 24:
            raise ValueError('계획할 개념 수는 1~24개로 선택하세요.')
        with self.mutex:
            if self.active:
                raise ValueError('이미 진행 중인 작업이 있습니다.')
            jid = uuid.uuid4().hex
            job = {'id': jid, 'action': action, 'mode': mode, 'status': 'queued',
                   'step': '', 'completed_steps': [], 'error': None, 'at': now()}
            if action == 'visual':
                job.update(file_id=options['file_id'],locator=options['locator'])
            self.jobs[jid] = job
            self.active = jid
            save(self.storage / 'jobs' / (jid + '.json'), job)
            threading.Thread(target=self._work, args=(jid, options), daemon=True).start()
            return copy.deepcopy(job)

    def _work(self,jid,options):
        # Publish terminal state only after file metadata and stage records are saved.
        job=copy.deepcopy(self.jobs[jid]);base=self.base(job['mode'])
        target=options.get('target','teacher') if job['action'] in ('read','understand','resume') else ('scope' if job['action']=='scope' else 'teacher')
        def progress(label):
            with self.mutex:
                job.update(status='running',step=label)
                self.jobs[jid].update(status='running',step=label)
                save(self.storage/'jobs'/(jid+'.json'),job)
        try:
            if job['action']=='visual':
                from .visual import analyze_page
                from .nvidia import NvidiaProvider
                row=self._file(options['file_id'])
                provider=NvidiaProvider(env_file=self.root/'.env',task='vision',timeout=90,
                    usage_path=self.workspace/row['target']/'usage_log.json')
                progress(row['name']+' · '+options['locator']+' 그림·문맥 분석')
                report=analyze_page(self.workspace/'uploads'/(row['id']+row['suffix']),
                    self.perception_path(row['id']),options['locator'],provider)
                files=self.files()
                for item in files:
                    if item['id']==row['id']:
                        item['status']='pending'
                        item.setdefault('visual_pages',{})[options['locator']]=report['content_hash']
                save(self.workspace/'files.json',files)
                job.update(status='done',outcome='complete',step='그림 해석 저장 · 원문 검토에서 확인하세요.')
            else:
                from .web_pipeline import execute
                execute(self,job,options,progress)
        except Exception as exc:
            # Infrastructure guard, not ordinary stage orchestration. Scope it to
            # this job's selected sources; an unrelated historical note is not success.
            from .stage_state import StageLedger
            ledger=StageLedger(base/target/'pipeline_state')
            selected={f.get('pipeline_source_id',f['id']):f.get('pipeline_input_hash',f['sha256']) for f in self.files() if f['target']==target
                and (not options.get('file_id') or f['id']==options['file_id'])}
            rows=[r for r in ledger.rows() if r['source_id'] in selected and r['input_hash']==selected[r['source_id']]]
            message=exc.message if isinstance(exc,ValidationError) else str(exc)
            committed=job['action'] not in ('plan','read','visual','structure') and any(
                r['stage']=='UNDERSTANDING' and r['status']=='complete' for r in rows)
            job.update(status='done' if committed else 'failed',
                outcome='partial_success' if committed else 'failed_before_understanding',
                error=self.clean(message),stage_tasks=self.clean(rows),
                stored_notes=len({r['note_id'] for r in rows if r['stage']=='UNDERSTANDING' and r['status']=='complete' and r['note_id']}),
                step='이해 노트는 저장됐습니다. 후속 작업에서 문제가 생겼습니다.' if committed else '기존 결과는 보존했습니다')
        finally:
            with self.mutex:
                job['finished_at']=now()
                save(self.storage/'jobs'/(jid+'.json'),job)
                self.jobs[jid]=copy.deepcopy(job)
                if self.active==jid:self.active=None

    def update_plan(self, payload):
        mode = payload.get('mode', 'workspace')
        path = self.base(mode) / 'current_plan.json'
        with self.mutex:
            if self.active:
                raise ValueError('진행 중인 작업이 끝난 뒤 변경하세요.')
            value = update_study_plan(path, payload.get('event_type'), payload.get('note', ''),
                                      payload.get('task_id'), payload.get('status'))
            return self.clean(value)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, body, content_type='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(self.server.store.clean(body), ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        try:
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, TimeoutError):
            # Closing/reloading a browser is not a failed document analysis.
            # Do not attempt a second error response on the already broken socket.
            self.close_connection=True

    def guarded(self, mutation=False):
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in allowed:
            raise ValueError('로컬 주소에서 접속하세요.')
        if mutation:
            origin = self.headers.get('Origin')
            if (self.headers.get('X-Backspace-Client') != 'web' or
                    (origin and origin not in {'http://' + h for h in allowed}) or
                    self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                raise ValueError('현재 작업공간에서 요청하세요.')

    def do_GET(self):
        try:
            self.guarded()
            route = urlsplit(self.path)
            query = parse_qs(route.query)
            if route.path == '/api/data':
                with self.server.store.mutex:
                    self.send(200, self.server.store.data(query.get('mode', ['demo'])[0]))
            elif route.path == '/api/config':
                from .perception import readiness
                values = dotenv_values(self.server.store.root / '.env')
                self.send(200, {'nvidia_ready': any(os.environ.get(k) or values.get(k) for k in
                    ('NVIDIA_API_KEY', 'NVIDIA_SUPER_API_KEY', 'NVIDIA_LIGHTNING_API_KEY')),
                    'jev_ready': bool(os.environ.get('TYPESAFE_API_KEY') or values.get('TYPESAFE_API_KEY')),
                    'max_file_mb': MAX_FILE//1024//1024, 'max_file_bytes':MAX_FILE,
                    'ocr':readiness(), 'local_only': True,
                    'runtime':{'loaded_revision':LOADED_BACKEND_REVISION,
                               'restart_required':LOADED_BACKEND_REVISION!=backend_revision()}})
            elif route.path=='/api/memory':
                from .understanding import list_saved_notes,search_saved_memory
                target=query.get('target',['teacher'])[0]
                if target not in ('teacher','scope'):raise ValueError('알 수 없는 자료 공간입니다.')
                folder=self.server.store.base(query.get('mode',['workspace'])[0])/target/'memory'
                search=query.get('query',[''])[0]
                if len(search)>1000:raise ValueError('검색 문장은 1000자 이하입니다.')
                source_id=query.get('source_id',[None])[0]
                current_fingerprint=None
                if query.get('file_id'):
                    row=self.server.store._file(query['file_id'][0])
                    if row['target']!=target:raise ValueError('자료 공간이 일치하지 않습니다.')
                    from .perception import source_from_document
                    document=self.server.store.perception(row['id'])
                    path=self.server.store.workspace/'uploads'/(row['id']+row['suffix'])
                    from .visual import attach_reports
                    from .understanding import source_fingerprint
                    current=attach_reports(source_from_document(path,document,KINDS[row['kind']],row['exam_id'] or None),
                        document,self.server.store.perception_path(row['id']))
                    source_id=current['id'];current_fingerprint=source_fingerprint(current)
                value=({'notes':search_saved_memory(folder,search,k=8)} if search else
                    list_saved_notes(folder,source_id=source_id,current_fingerprint=current_fingerprint))
                self.send(200,self.server.store.clean(value))
            elif route.path.startswith('/api/perception/'):
                parts=route.path.strip('/').split('/')
                if len(parts) not in (3,5) or not re.fullmatch('[a-f0-9]{24}',parts[2]):
                    raise ValueError('잘못된 인식 결과 요청입니다.')
                fid=parts[2]
                doc=self.server.store.perception(fid)
                if len(parts)==3:
                    from .visual import read_report
                    doc['visual_analysis']={p['locator']:r for p in doc['pages']
                        if (r:=read_report(self.server.store.perception_path(fid),doc,p['locator']))}
                    self.send(200,doc)
                elif parts[3]=='visual-images' and re.fullmatch('[a-f0-9]{24}',parts[4]):
                    from .visual import read_report
                    reports=[r for p in doc['pages'] if (r:=read_report(self.server.store.perception_path(fid),doc,p['locator']))]
                    name='visual-'+parts[4]+'.jpg'
                    if not any(i['file']==name for r in reports for i in r['images']):
                        raise ValueError('분석에 사용한 이미지를 찾을 수 없습니다.')
                    self.send(200,(self.server.store.perception_path(fid).parent/name).read_bytes(),'image/jpeg')
                elif parts[3]=='assets' and re.fullmatch('pa_[a-f0-9]{20}',parts[4]):
                    asset=next((a for p in doc['pages'] for a in p['assets'] if a['id']==parts[4]),None)
                    if not asset:
                        raise ValueError('원본 이미지 영역을 찾을 수 없습니다.')
                    path=self.server.store.perception_path(fid).parent/asset['file']
                    self.send(200,path.read_bytes(),'image/png')
                else:
                    raise ValueError('잘못된 이미지 요청입니다.')
            elif route.path.startswith('/api/jobs/'):
                jid = route.path.rsplit('/', 1)[-1]
                with self.server.store.mutex:
                    job = self.server.store.jobs.get(jid)
                    self.send(200 if job else 404, job or {'error': '작업을 찾을 수 없습니다.'})
            elif route.path == '/api/download':
                data = self.server.store.data(query.get('mode', ['demo'])[0])
                kind = query.get('kind', ['model'])[0]
                if kind not in ('model', 'plan') or not data[kind]:
                    raise ValueError('저장된 결과가 없습니다.')
                self.send(200, data[kind])
            else:
                if route.path.startswith('/vendor/'):
                    name = route.path.rsplit('/', 1)[-1]
                    if name not in ('gsap.min.js', 'Flip.min.js', 'ScrollTrigger.min.js', 'SplitText.min.js', 'DrawSVGPlugin.min.js'):
                        self.send(404, {'error': '파일 없음'})
                        return
                    path = self.server.store.root / 'node_modules/gsap/dist' / name
                else:
                    name = 'index.html' if route.path == '/' else unquote(route.path).lstrip('/')
                    path = (STATIC / name).resolve()
                    if STATIC.resolve() not in path.parents:
                        self.send(404, {'error': '파일 없음'})
                        return
                if not path.is_file():
                    self.send(404, {'error': '파일 없음. npm install 실행 여부를 확인하세요.'})
                    return
                mime = {'.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml'}.get(path.suffix)
                self.send(200, path.read_bytes(), (mime or mimetypes.guess_type(path)[0] or 'application/octet-stream') + '; charset=utf-8')
        except (ValueError, OSError, KeyError) as exc:
            self.send(400, {'error': self.server.store.clean(str(exc))})

    def do_POST(self):
        try:
            self.guarded(mutation=True)
            size = int(self.headers.get('Content-Length', '0'))
            route = urlsplit(self.path)
            maximum = MAX_FILE if route.path == '/api/upload' else 32 * 1024
            if not 0 < size <= maximum:
                self.close_connection=True
                self.send(413,{'error':'파일은 100MB 이하로 올려주세요.' if route.path=='/api/upload' else '요청 크기를 확인하세요.'})
                return
            if route.path == '/api/upload':
                self.connection.settimeout(120)
                query = {k: v[0] for k, v in parse_qs(route.query).items()}
                value = self.server.store.upload_stream(self.rfile,size, query.get('filename', ''), query.get('target'),
                    query.get('kind'), query.get('exam_id', ''), query.get('material_type', 'unspecified'))
            else:
                body=self.rfile.read(size)
                if len(body)!=size:
                    raise ValueError('파일 전송이 완료되지 않았습니다.')
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError('요청 객체가 필요합니다.')
                if route.path == '/api/jobs':
                    value = self.server.store.start(payload.get('action'), payload)
                elif route.path == '/api/plan/event':
                    value = self.server.store.update_plan(payload)
                elif route.path == '/api/perception/review':
                    value = self.server.store.review(payload)
                else:
                    self.send(404, {'error': '요청 없음'})
                    return
            self.send(200, value)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.send(400, {'error': self.server.store.clean(str(exc))})


def make_server(port=8766, store=None):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.store = store or WebStore()
    return server


def main():
    parser = argparse.ArgumentParser(description='Backspace local Teacher Studio')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    server = make_server(args.port)
    print(f'Backspace: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
