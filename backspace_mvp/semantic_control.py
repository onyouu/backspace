"""Jev judges bounded states; Python applies conservative, auditable routing."""
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .model import read_json
from .pipeline import digest, save, writable
from .jev_questions import NOTE_VERSION, HYPOTHESIS_VERSION, note_questions, hypothesis_questions


def thresholds():
    path = Path(os.environ.get('JEV_THRESHOLDS_FILE') or Path(__file__).with_name('jev_thresholds.json'))
    config = read_json(path)
    for variable,key in {'JEV_SLOW_REASONING_THRESHOLD':'noul_yes',
                         'JEV_LOW_CONFIDENCE_THRESHOLD':'choice_confidence',
                         'JEV_GRAPH_PROJECTION_THRESHOLD':'graph_yes'}.items():
        if os.environ.get(variable):config[key]=float(os.environ[variable])
    for key in ('noul_yes','noul_no','choice_probability','choice_confidence','graph_yes','graph_no'):
        if not isinstance(config[key],(int,float)) or not 0 <= config[key] <= 1:
            raise ValueError('Jev threshold must be in [0,1].')
    if config['noul_no'] >= config['noul_yes'] or config['graph_no'] >= config['graph_yes']:
        raise ValueError('Jev uncertain interval must be nonempty.')
    if config['max_state_chars'] < 1000 or not 1 <= config['max_related_notes'] <= 3:
        raise ValueError('Jev state bounds are invalid.')
    return config


class SemanticControl:
    def __init__(self, folder, *, provider=None, config=None):
        self.folder=writable(folder);self.provider=provider
        self.config=copy.deepcopy(config) if config is not None else thresholds()
        self.threshold_version=self.config['version']+'-'+digest(self.config)[:12]

    def _save(self, path, value):
        from jsonschema import Draft202012Validator
        Draft202012Validator(read_json(Path(__file__).parent/'schemas/jev_decision.schema.json')).validate(value)
        save(path,value)

    def _provider(self):
        if self.provider is None:
            from .jev import JevProvider
            self.provider=JevProvider(usage_path=self.folder.parent/'usage_log.json')
        return self.provider

    def noul(self, answer, *, graph=False):
        if not answer:return None
        low,high=(self.config['graph_no'],self.config['graph_yes']) if graph else (self.config['noul_no'],self.config['noul_yes'])
        p=answer['noul']
        return True if p >= high else False if p <= low else None

    def choice(self, answer):
        if not answer:return None
        selected=answer['choice']
        return selected if (answer['confidence'] >= self.config['choice_confidence']
            and answer['probabilities'][selected] >= self.config['choice_probability']) else None

    def judge(self, kind, state, questions, version, *, note_ids=(), hypothesis_ids=()):
        from .jev import JevProvider
        configured_model=getattr(self.provider,'model',None) or os.environ.get('JEV_MODEL','jev-latest')
        state_hash=digest(state)
        identity=digest([kind,state_hash,questions,version,self.threshold_version,configured_model])
        path=self.folder/kind/(identity+'.json')
        previous=None
        if path.exists():
            previous=read_json(path)
            if previous.get('status')=='success':
                JevProvider.validate_response({'model':previous['model'],'answers':previous['raw_answers']},questions)
                return previous
            if kind.startswith('teacher_'):
                save(path.parent/'attempt_history'/f"{identity}-a{previous.get('attempt_count', 1)}.json",previous)
        value={'decision_id':identity,'decision_type':kind,'state_hash':state_hash,
            'question_version':version,'question_versions':{q:q+'_'+version for q in questions},
            'question_hash':digest(questions),'questions':questions,'model':None,'configured_model':configured_model,
            'raw_answers':{},'probabilities':{},'confidence':{},'threshold_version':self.threshold_version,
            'thresholds':self.config,'final_route':'safe_fallback','created_at':datetime.now(timezone.utc).isoformat(),
            'related_note_ids':list(note_ids),'related_hypothesis_ids':list(hypothesis_ids)}
        value['attempt_count']=previous.get('attempt_count',1)+1 if previous else 1
        try:
            if len(json.dumps(state,ensure_ascii=False)) > self.config['max_state_chars']:
                raise ValueError('bounded_state_exceeded')
            value['state_snapshot']=state
            result=self._provider().decide(state,questions,stage=kind)
            JevProvider.validate_response(result,questions)
            value.update(status='success',model=result['model'],raw_answers=copy.deepcopy(result['answers']),usage=result.get('usage'))
            value['probabilities']={q:(a['noul'] if a['type']=='noul' else a['probabilities']) for q,a in result['answers'].items()}
            value['confidence']={q:(None if a['type']=='noul' else a['confidence']) for q,a in result['answers'].items()}
        except (ValueError,TimeoutError,OSError,TypeError,KeyError):
            # No provider error bodies/credentials; failure is not cached as rejection.
            value.update(status='fallback',error='decision_unavailable_or_state_invalid')
        self._save(path,value)
        return value

    def route_note(self, content, metadata, related, *, represented_relations=None, teacher_summary=None):
        related=related[:self.config['max_related_notes']]
        related=[{**{k:r[k] for k in ('id','content','topic','source_type','provenance')},
            'amem':{k:r.get('amem',{}).get(k) for k in ('keywords','context','tags')}} for r in related]
        topics=list(dict.fromkeys(' / '.join(r['topic']) for r in related))
        state={'new_note':{'content':content,'topic_candidate':metadata['topic'],
                          'source_type':metadata['source_type'],'source':metadata['provenance']},
               'related_notes':related,'current_topics':topics,
               'represented_relations':represented_relations or [],'teacher_summary':teacher_summary or {}}
        value=self.judge('note_router',state,note_questions(topics),NOTE_VERSION,
                         note_ids=[metadata['id'],*[r['id'] for r in related]])
        answers=value['raw_answers'];relation=self.choice(answers.get('relation'))
        topic=self.choice(answers.get('topic'))
        # Unknown judgments, contradictory evidence and uncertain relation/topic need slow reasoning.
        slow=(self.noul(answers.get('needs_slow_reasoning')) is not False
              or relation is None or topic in (None,'uncertain') or relation in ('extends','contradicts'))
        graph=relation=='contradicts' or any(self.noul(answers.get(q),graph=True) is not False
                  for q in ('graph_relation','graph_teacher','graph_assessment'))
        value['final_route']={'needs_slow_reasoning':slow,'project_graph':graph,'relation':relation,
            'duplicate':self.noul(answers.get('duplicate')),'topic':topic,
            'selected_topic':topics[int(topic.split('_')[1])].split(' / ') if topic and topic.startswith('topic_') else metadata['topic'],
            'teacher_signal':self.noul(answers.get('teacher_signal')),
            'exam_related':self.noul(answers.get('exam_related')),
            'link_candidate_id':related[0]['id'] if related and relation=='reinforces' and not slow else None}
        self._save(self.folder/'note_router'/(value['decision_id']+'.json'),value)
        # Same request, separate graph audit; no additional API invocation.
        projection={**value,'decision_type':'graph_gate','bundle_decision_id':value['decision_id'],
                    'final_route':'project' if graph else 'notes_only'}
        self._save(self.folder/'graph_gate'/(value['decision_id']+'.json'),projection)
        return value

    def validate_hypothesis(self, hypothesis, evidence):
        state={'hypothesis':{k:hypothesis[k] for k in ('id','statement','applicable_context')},
               'evidence':evidence,'statistics':hypothesis.get('structural_statistics',[])}
        value=self.judge('hypothesis_validation',state,hypothesis_questions(),HYPOTHESIS_VERSION,
                         hypothesis_ids=[hypothesis['id']])
        answers=value['raw_answers'];relation=self.choice(answers.get('relation'));scope=self.choice(answers.get('scope'))
        strength=answers.get('strength',{})
        status=relation if (relation is not None and scope is not None
            and strength.get('confidence',0) >= self.config['choice_confidence']) else 'needs_review'
        # Strength remains a rubric score; never convert to probability/importance.
        value['final_route']={'status':status,'scope':scope,
            'needs_reanalysis':self.noul(answers.get('reanalysis')) is not False,
            'strength_score':strength.get('score'),'strength_confidence':strength.get('confidence')}
        self._save(self.folder/'hypothesis_validation'/(value['decision_id']+'.json'),value)
        return {'decision_id':value['decision_id'],'question_version':HYPOTHESIS_VERSION,
                'model':value['model'],'decision_status':value['status'],
                'summary_status':status,'evidence_relation':relation,
                **{k:v for k,v in value['final_route'].items() if k!='status'}}

    def future_gate(self, kind, state):
        from .jev_questions import future_questions, FUTURE_VERSION
        value=self.judge(kind,state,future_questions(kind),FUTURE_VERSION)
        if kind=='planning_gate':
            value['final_route']=self.choice(value['raw_answers'].get('route')) or 'full_replan'
        else:
            value['final_route']='review_required'
        self._save(self.folder/kind/(value['decision_id']+'.json'),value)
        return value


def automatic_control(provider, folder):
    from .nvidia import NvidiaProvider
    if isinstance(NvidiaProvider,type) and isinstance(provider,NvidiaProvider) and os.environ.get('BACKSPACE_JEV_CONTROL_ENABLED','1') != '0':
        return SemanticControl(folder)
    return None
