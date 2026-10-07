"""Small model contracts; IDs, graph wiring and state commits are application-owned."""
import copy
import json
import unicodedata
import re
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError
from .pipeline import digest, save, empty_dataset
from .model import validate, read_json


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


TEXT = {'type': 'string', 'minLength': 1}
STRINGS = {'type': 'array', 'items': TEXT, 'minItems': 1}
SEGMENT = obj({'questions': {'type': 'array', 'minItems': 1, 'items': obj({
    'number': TEXT, 'text': TEXT, 'context': {'type': 'string'}, 'complete': {'type': 'boolean'}})}})


def normalize(label):
    return ' '.join(unicodedata.normalize('NFKC', label).split()).casefold()


class StagedExtractor:
    VERSION = 'grounded-2.3'

    def __init__(self, provider, base, source, checkpoint_dir, answer_sources=None, answer_mapping=None, progress=None, visual_inputs=None, understanding_units=None):
        self.provider, self.base, self.source = provider, base, source
        self.progress = progress
        self.visual_inputs = visual_inputs or {}
        self.understanding_units = understanding_units
        self.folder = Path(checkpoint_dir) / source['id']
        self.concepts = copy.deepcopy(base['concepts'])
        self.used = {}
        self.material_observations = []
        self.answer_sources = answer_sources or []
        self.answer_mapping = answer_mapping or {}
        self.used_answer_keys = set()
        self.manifest = {'source_id': source['id'], 'stages': []}

    def call(self, stage, prompt, schema, tokens, check, provider=None):
        provider = provider or self.provider
        identity = digest([self.VERSION, prompt, schema, tokens,
            getattr(provider, 'model', 'fixture'), getattr(provider, 'fallback', None), getattr(provider, 'max_tokens', None),
            getattr(provider, 'reasoning_effort', None)])
        path = self.folder / (identity + '.json')
        if not path.exists():
            # A previously received candidate may now pass a deterministic
            # repair. Revalidate every field and citation before reusing it.
            for failed in sorted(self.folder.glob(identity + '.failed-*.json'), reverse=True):
                previous = read_json(failed)
                candidate = previous['result']
                try:
                    Draft202012Validator(schema).validate(candidate)
                    check(candidate)
                    Draft202012Validator(schema).validate(candidate)
                except (ValueError, ValidationError):
                    continue
                save(path, {'result': candidate, 'model': previous.get('model'),
                            'recovered_from': failed.name})
                break
        if self.progress:
            self.progress(stage, path.exists())
        from .nvidia import NvidiaProvider
        if path.exists():
            entry = read_json(path)
            value = entry['result']
            cached = True
            if isinstance(provider, NvidiaProvider) and entry.get('model') in (provider.model, provider.fallback):
                provider.last_model = entry['model']
                provider.preferred_model = entry['model']
        else:
            current_prompt = prompt
            for attempt in range(2):
                if isinstance(provider, NvidiaProvider):
                    value = provider.complete(current_prompt, schema, stage=stage + (':repair' if attempt else ''), max_tokens=tokens)
                else:
                    value = provider.complete(current_prompt, schema)
                Draft202012Validator(schema).validate(value)
                try:
                    check(value)
                    break
                except ValueError as exc:
                    save(self.folder / (identity + f'.failed-{attempt}.json'),
                        {'stage': stage, 'validation_error': str(exc), 'result': value,
                         'model': getattr(provider, 'last_model', None)})
                    if attempt:
                        raise
                    previous = ('\n이전 결과: '+json.dumps(value,ensure_ascii=False)) if self.understanding_units is None else ''
                    current_prompt = prompt + '\n검증 오류: ' + str(exc) + previous + '\n이 오류만 수정하고 제한된 범위의 JSON 분석 결과를 다시 반환하세요. 원문이나 근거를 바꾸지 마세요.'
            cached = False
        Draft202012Validator(schema).validate(value)
        check(value)
        if not cached:
            save(path, {'result': value, 'model': getattr(provider, 'last_model', None)})
        self.manifest['stages'].append({'stage': stage, 'cached': cached,
            'checkpoint': path.name, 'model': entry.get('model') if cached else getattr(provider, 'last_model', None)})
        self.persist_manifest()
        return value

    def persist_manifest(self):
        save(self.folder / 'manifest.json', self.manifest)

    def review_call(self, *args):
        from .nvidia import NvidiaProvider
        if not hasattr(self, '_review_provider'):
            self._review_provider = (NvidiaProvider(env_file=self.provider.env_file,
                timeout=self.provider.timeout, task='review', usage_path=self.provider.usage_path)
                if isinstance(self.provider, NvidiaProvider) else self.provider)
        return self.call(*args, provider=self._review_provider)

    def evidence_review_call(self, stage, prompt, schema, tokens, check, *, evidence):
        """Text evidence verdicts are decisions, never an extra NVIDIA generation."""
        from .nvidia import NvidiaProvider
        if not isinstance(self.provider, NvidiaProvider):
            return self.review_call(stage, prompt, schema, tokens, check)
        from .semantic_control import SemanticControl
        from .jev_questions import choice
        control = getattr(self, '_evidence_control', None)
        if control is None:
            control = self._evidence_control = SemanticControl(self.folder / 'jev_evidence')
        criteria = {
            'supported': 'Every mechanism, direction and condition is explicitly supported by the supplied source.',
            'contradicted': 'The supplied source explicitly says the opposite under the same conditions.',
            'insufficient_evidence': 'Source is relevant but incomplete or ambiguous.',
            'domain_knowledge_needs_review': 'Requires external knowledge or mechanisms absent from the citations.'}
        questions = {f'verdict_{i}': choice('Judge evidence row '+str(i)+
            '. Use only its source and statement, including all conditions; plausible science alone is not source support.', criteria)
            for i in range(len(evidence))}
        if not questions:
            return {'verdicts': []}
        decision = control.judge('source_evidence', {'evidence': evidence}, questions, 'source-evidence-1')
        if decision['status'] != 'success':
            raise ConnectionError('Jev source evidence decision_unavailable; checkpoint preserved')
        verdicts = []
        for i in range(len(evidence)):
            status = control.choice(decision['raw_answers'].get(f'verdict_{i}'))
            if status is None:
                status = 'insufficient_evidence'
            verdicts.append({'index': i, 'status': status,
                'reason': 'Jev 원문 판정: '+status+' · '+decision['decision_id'][:12]})
        result = {'verdicts': verdicts}
        Draft202012Validator(schema).validate(result); check(result)
        path = self.folder / ('jev-evidence-'+decision['decision_id']+'.json')
        cached = path.exists()
        if not cached: save(path, {'result': result, 'model': decision['model'], 'decision_id': decision['decision_id']})
        self.manifest['stages'].append({'stage': stage, 'cached': cached,
            'checkpoint': path.name, 'model': decision['model'], 'provider': 'Jev'})
        self.persist_manifest()
        return result

    def concept(self, label):
        matches = [c for c in self.concepts if normalize(label) in {normalize(s) for s in [c['label'], *c['aliases']]}]
        if len(matches) > 1:
            raise ValueError('개념 이름이 여러 ID에 대응합니다. 개념 목록을 검토하세요.')
        if matches:
            value = matches[0]
        else:
            value = {'id': 'c_' + digest(normalize(label))[:16], 'label': label, 'aliases': []}
            self.concepts.append(value)
        self.used[value['id']] = value
        return value['id']

    def evidence(self, locator, quote):
        return {'source_id': self.source['id'], 'locator': locator, 'quote': quote}

    def pages(self):
        if self.understanding_units is not None and self.source['kind']=='learning_material':
            from .understanding import split_units
            for unit in self.understanding_units:
                decision=unit.get('semantic_control',{})
                if decision.get('status')=='success' and decision.get('final_route',{}).get('project_graph') is False:
                    self.manifest.setdefault('skipped_graph_units',[]).append({
                        'note_id':unit['id'],'locator':unit['locator'],
                        'decision_id':decision['decision_id'],'reason':'jev_notes_only',
                        'source_span':{'start':unit['start'],'end':unit['end']}})
                    self.persist_manifest()
                    if self.progress:self.progress('이해 노트 보존·그래프 생략 '+unit['locator'],True)
                    continue
                for _,_,text in split_units(unit['text'],900):
                    yield {'locator':unit['locator'],'text':text,'understanding_note':unit['content'],
                           'understanding_note_id':unit['id'],'understanding_content_hash':unit['content_hash']}
            return
        for page in self.source['excerpts']:
            if not page['text'].strip():
                continue
            if len(page['text']) > 8000:
                if self.source['kind']=='exam':
                    # Long/ambiguous exam pages stay visible in perception; do not guess boundaries.
                    self.manifest.setdefault('needs_review_pages',[]).append(page['locator'])
                    self.source.setdefault('perception',{}).setdefault('blocked_pages',[]).append(page['locator'])
                    continue
                current=''
                for part in page['text'].split('\n\n'):
                    if len(part)>7000:
                        raise ValueError(f"{page['locator']}: 한 텍스트 블록이 너무 깁니다. 인식 결과에서 분리해 주세요.")
                    if current and len(current)+len(part)+2>7000:
                        yield {'locator':page['locator'],'text':current}
                        current=''
                    current=current+'\n\n'+part if current else part
                if current:
                    yield {'locator':page['locator'],'text':current}
                continue
            yield page

    def extract(self):
        relations, questions = [], []
        for page in self.pages():
            if self.source['kind'] == 'exam':
                questions.extend(self.exam(page))
            else:
                relations.extend(self.material(page))
        if self.source['kind'] == 'learning_material':
            self.source['material_analysis_version'] = 'teacher-material-1.0'
            if self.understanding_units is not None:
                skipped=self.manifest.get('skipped_graph_units',[])
                self.source['graph_projection']={'total_notes':len(self.understanding_units),
                    'projected_notes':len(self.understanding_units)-len(skipped),
                    'notes_only':len(skipped),'skipped_units':skipped,
                    'meaning':'Graph frequency covers projected notes only; all notes remain in memory.'}
        if set(self.answer_mapping) != self.used_answer_keys:
            raise ValueError('정답·해설 매핑에 실제 분리된 문항과 대응하지 않는 항목이 있습니다.')
        materials = [s for s in self.base['sources'] if s['kind'] == 'learning_material'] if self.source['kind'] == 'exam' else []
        addition = {**empty_dataset(), 'scope': self.base['scope'], 'sources': [*materials, *self.answer_sources, self.source],
            'concepts': list(self.used.values()), 'material_relations': list({r['id']:r for r in relations}.values()), 'questions': questions,
            'material_observations': self.material_observations,
            'notes': ['AI 분석은 검토 전 가설이며, 원문 인용 검증은 과학적 정확성 검증을 대신하지 않습니다.']}
        return validate(addition)

    def material(self, page):
        from .grounded import extract_material
        from .nvidia import SemanticReductionRequired
        marker=self.folder/(digest([self.VERSION,'material_reduction',page,getattr(self.provider,'model','fixture')])+'.reduction.json')
        def smaller(reason=None):
            depth=page.get('reduction_depth',0)
            if depth>=2 or len(page['text'])<=200:
                record=read_json(marker) if marker.exists() else {}
                raise SemanticReductionRequired('작은 자료 구간도 분석을 완료하지 못했습니다. 보존된 원문·이해 노트를 검토하세요.',
                    stage=record.get('stage','material:'+page['locator']),reason=reason or record.get('reason','timeout'))
            from .understanding import split_units
            relations=[]
            for _,_,text in split_units(page['text'],max(100,len(page['text'])//2)):
                relations.extend(self.material({**page,'text':text,'reduction_depth':depth+1}))
            return relations
        if marker.exists():
            record=read_json(marker)
            if record.get('action')=='split_source':return smaller()
            # A prior leaf timeout must not permanently poison every explicit resume.
            # Retry the same bounded leaf once in this invocation; never loop inside it.
        before=(copy.deepcopy(self.concepts),copy.deepcopy(self.used),copy.deepcopy(self.material_observations))
        try:return extract_material(self,page)
        except SemanticReductionRequired as exc:
            self.concepts,self.used,self.material_observations=before
            depth=page.get('reduction_depth',0)
            record={
                'stage':exc.stage,'reason':exc.reason,'input_chars':len(page['text']),
                'depth':depth,'action':'split_source' if depth<2 and len(page['text'])>200 else 'needs_review'}
            save(marker,record)
            self.manifest.setdefault('semantic_reductions',[]).append(record)
            self.persist_manifest()
            return smaller(exc.reason)

    def exam(self, page):
        prompt = ('시험 원문을 문항/소문항별로 분리하세요. 답이나 분석을 쓰지 마세요. text는 번호를 포함한 원문의 연속된 부분문자열, '
            'context는 필요한 공통 지문을 원문 그대로 넣거나 빈 문자열로 둡니다. 페이지 밖 지문/그림/이어지는 문장이 필요하면 complete=false입니다. '
            '완성된 일반 문항은 complete=true입니다. number에는 원문 문항 번호만 쓰고 Q 같은 접두부를 붙이지 마세요. '
            '서로 다른 번호의 문항을 하나로 합치지 마세요.\n원문:\n' + page['text'])
        def check(value):
            occupied = []
            numbers = set()
            for q in value['questions']:
                q['number'] = q['number'].strip().strip('(). ')
                if not q['number']:
                    raise ValueError('문항 번호가 비어 있습니다.')
                if not q['complete']:
                    raise ValueError('불완전한 문항입니다. 필요한 지문/그림 설명을 포함해 입력하세요.')
                if q['text'] not in page['text'] or q['context'] not in page['text']:
                    raise ValueError('문항 분리 결과가 원문과 다릅니다.')
                if q['number'] in numbers:
                    raise ValueError('한 페이지에 중복 문항 번호가 있습니다.')
                numbers.add(q['number'])
                start = page['text'].find(q['text'])
                end = start + len(q['text'])
                if any(start < b and a < end for a, b in occupied):
                    raise ValueError('문항의 원문 범위가 겹칩니다.')
                occupied.append((start, end))
                major = list(re.finditer(r'(?m)^\s*(\d+)\.\s+', q['text']))
                if len(major) > 1:
                    raise ValueError('서로 다른 번호의 시험 문항을 하나의 question에 합쳤습니다.')
                if major and major[0][1] != q['number']:
                    raise ValueError('문항 번호가 인용한 원문 번호와 다릅니다.')
            # Numbered question starts must be covered by a question span, not just common context.
            for match in re.finditer(r'(?m)^\s*\d+[.)]\s+', page['text']):
                anchor = match.end() - 1
                if not any(start <= anchor < end for start, end in occupied):
                    raise ValueError('번호가 있는 시험 문항이 분리 결과에서 누락되었습니다.')
            requested = {number for (loc, number) in self.answer_mapping if loc == page['locator']}
            if not requested <= numbers:
                raise ValueError('정답·해설의 문항 번호와 분리 결과가 대응하지 않습니다.')
        segments = self.call('segment:' + page['locator'], prompt, SEGMENT, 2048, check)
        return [self.question(page['locator'], q) for q in segments['questions']]

    def question(self, locator, segment):
        from .grounded import extract_question
        return extract_question(self, locator, segment)
