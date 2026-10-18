import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from backspace_mvp.efficient_teacher import (active_materials,corpus_hash,units_for,checked_extraction,project,commit_notes)
from backspace_mvp.pipeline import empty_dataset,digest
from backspace_mvp.request_budget import RequestBudget,BudgetDeferred,quota_error
from backspace_mvp.gemini import GeminiProvider


class EfficientTeacherTests(unittest.TestCase):
    def test_bounded_selection_keeps_all_dimensions_and_source_diversity(self):
        from backspace_mvp.efficient_teacher import candidate_context
        dimensions=['assessment_criterion','concept_connection','concept_priority','reasoning_demand']
        registry={}
        for dimension in dimensions:
            for sid in range(9):
                eid=f'{dimension}_{sid}'
                registry[eid]={'id':eid,'origin_id':str(sid),'details':{'dimension':dimension,'observation':'구체적인 요구를 관찰했다. '*15},
                    'citations':[{'raw_evidence':'원문에서 설명 순서를 요구한다. '*30}]}
        selected=candidate_context(registry,40)
        self.assertEqual({e['dimension'] for e in selected},set(dimensions))
        self.assertEqual(len({e['dimension'] for e in selected[:4]}),4)
        self.assertGreaterEqual(len({e['source'] for e in selected}),6)
        self.assertLessEqual(sum(len(json.dumps(e,ensure_ascii=False).encode()) for e in selected),14000)

    def test_numbered_evidence_preserves_original_and_rejects_unknown_id(self):
        from backspace_mvp.efficient_teacher import evidence_input,expand_evidence,exact_ref
        original=('첫 조건\nDNA 복제에 프라이머가 필요하다.\n'*60)+'마지막 문장'
        units=[{'id':'p1:20','locator':'p1','start':20,'end':20+len(original),'text':original}]
        wire,registry=evidence_input(units)
        self.assertEqual(''.join(p['text'] for p in wire[0]['passages']),original)
        self.assertTrue(all(len(p['text'])<=800 for p in wire[0]['passages']))
        eid=wire[0]['passages'][0]['evidence_id']
        result=expand_evidence({'concepts':[{'ref':{'evidence_id':eid}}],'relations':[],'teacher_cues':[]},registry)
        ref=exact_ref(result['concepts'][0]['ref'],units,{'id':'source'})
        self.assertEqual(ref['start_offset'],20)
        with self.assertRaises(ValueError):expand_evidence({'concepts':[{'ref':{'evidence_id':'invented'}}],'relations':[],'teacher_cues':[]},registry)

    def fixture(self):
        source={'id':'s1','kind':'learning_material','title':'자료','path':'test.txt','sha256':'a'*64,'format':'txt',
            'extraction_status':'text_extracted_needs_review','excerpts':[{'locator':'p1','text':'DNA 복제에는 프라이머가 필요하다. 방향을 비교하고 설명하세요.'}]}
        units=list(units_for(source));ref={'unit':units[0]['id'],'quote':source['excerpts'][0]['text']}
        result={'notes':[{'unit':units[0]['id'],'title':'복제 조건','topic':'복제','content':'프라이머의 필요성과 방향을 설명한다.','uncertainties':[]}],
            'concepts':[{'label':label,'surface':label,'confidence':.9,'ref':ref} for label in ['DNA 복제','프라이머']],
            'relations':[{'from':'DNA 복제','to':'프라이머','relation':'requires','statement':'DNA 복제는 프라이머를 요구한다.','conditions':[],'ref':ref}],
            'teacher_cues':[{'dimension':'reasoning_demand','observation':'방향 비교와 설명을 요구한다.','ref':ref}]}
        return source,units,result

    def test_evaluation_and_superseded_sources_do_not_change_training_hash(self):
        rows=[{'id':'one','target':'teacher','kind':'material','sha256':'a'},{'id':'exam','target':'evaluation','kind':'exam','sha256':'b'}]
        original=corpus_hash(rows);rows[1]['sha256']='changed'
        self.assertEqual(corpus_hash(rows),original)
        rows.append({**rows[0],'id':'duplicate'})
        self.assertEqual(len(active_materials(rows)),1)
        rows[-1]['excluded_from_model']=True
        self.assertEqual(active_materials(rows)[0]['id'],'one')

    def test_hallucinated_quote_is_rejected_and_unreviewed_relation_not_projected(self):
        source,units,result=self.fixture();bad=copy.deepcopy(result['teacher_cues'][0]);bad['ref']['quote']='시험에 반드시 출제한다'
        result['teacher_cues'].append(bad)
        packet=checked_extraction(result,units,source)
        self.assertEqual(len(packet['teacher_cues']),1);self.assertEqual(len(packet['rejected']),1)
        data=empty_dataset();project(data,source,[packet]);self.assertEqual(data['material_relations'],[])
        packet['relations'][0]['verified']=True
        project(data,source,[packet]);before=digest(data);project(data,source,[packet])
        self.assertEqual(digest(data),before);self.assertEqual(len(data['material_relations']),1)

    def test_note_preserves_exact_offsets_and_replay(self):
        source,units,result=self.fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);existing={}
            first=commit_notes(root,source,units,result,existing)
            second=commit_notes(root,source,units,result,existing)
            self.assertEqual(first,second)
            record=json.loads(next((root/'memory/notes').glob('*.json')).read_text(encoding='utf-8'))
            p=record['provenance'];self.assertEqual(source['excerpts'][0]['text'][p['span']['start']:p['span']['end']],p['quote'])

    def test_out_of_subject_text_is_preserved_as_note_but_not_graph_evidence(self):
        source,units,result=self.fixture();result['notes'][0]['in_scope']=False
        packet=checked_extraction(result,units,source)
        self.assertEqual(len(packet['notes']),1)
        for field in ('concepts','relations','teacher_cues'):self.assertEqual(packet[field],[])

    def test_shared_budget_reservations_wait_and_close_connections(self):
        tick=[1800000000.]
        def sleep(seconds):tick[0]+=seconds
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'BACKSPACE_API_RPM':'1','BACKSPACE_API_TPM':'100','BACKSPACE_API_RPD':'3'}):
            a=RequestBudget(Path(d),'test',clock=lambda:tick[0],sleep=sleep)
            b=RequestBudget(Path(d),'test',clock=lambda:tick[0],sleep=sleep)
            a.reserve(70);identity,wait=b.reserve(40)
            self.assertGreaterEqual(wait,60);b.reconcile(identity,10)
            with self.assertRaises(BudgetDeferred):b.reserve(101)

    def test_cached_result_avoids_network_and_changes_invalidate(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GEMINI_API_KEY':'test','GEMINI_MODEL':'gemini-3.6-flash',
                'GEMINI_LOG_DIR':str(Path(d)/'logs'),'BACKSPACE_API_RPM':'100'}):
            p=GeminiProvider(env_file=Path(d)/'none.env')
            def response(*a,**k):return io.BytesIO(json.dumps({'candidates':[{'content':{'parts':[{'text':'확인'}]},'finishReason':'STOP'}],
                    'usageMetadata':{'promptTokenCount':3,'candidatesTokenCount':2,'totalTokenCount':5}}).encode())
            with patch('urllib.request.urlopen',side_effect=response) as network:
                self.assertEqual(p.complete_text('같은 자료'),'확인');p.complete_text('같은 자료')
                self.assertEqual(network.call_count,1);self.assertEqual(p.attempts[-1]['status'],'cache_hit')
                p.complete_text('바뀐 자료');self.assertEqual(network.call_count,2)
                p.complete_text('같은 자료',max_tokens=200);self.assertEqual(network.call_count,3)

    def test_server_retry_and_daily_quota_metadata(self):
        seconds,reason=quota_error(json.dumps({'error':{'details':[{'@type':'google.rpc.RetryInfo','retryDelay':'12s'}]}}))
        self.assertEqual((seconds,reason),(12,'rate_limit'))
        _,reason=quota_error(json.dumps({'error':{'details':[{'violations':[{'quotaId':'GenerateRequestsPerDay'}]}]}}))
        self.assertEqual(reason,'daily_quota')

    def test_transient_503_retries_but_does_not_cache_failure(self):
        import urllib.error
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GEMINI_API_KEY':'test','GEMINI_MODEL':'gemini-3.6-flash','GEMINI_LOG_DIR':str(Path(d)/'logs')}):
            provider=GeminiProvider(env_file=Path(d)/'none.env')
            ok=io.BytesIO(json.dumps({'candidates':[{'content':{'parts':[{'text':'재개 성공'}]},'finishReason':'STOP'}],
                'usageMetadata':{'promptTokenCount':3,'candidatesTokenCount':2,'totalTokenCount':5}}).encode())
            error=urllib.error.HTTPError('https://provider.invalid',503,'unavailable',{},io.BytesIO(b'{}'))
            with patch('urllib.request.urlopen',side_effect=[error,ok]) as network,patch.object(RequestBudget,'reserve',return_value=(1,0)),patch.object(RequestBudget,'defer') as cooldown:
                self.assertEqual(provider.complete_text('503 retry'),'재개 성공')
                self.assertEqual(network.call_count,2);cooldown.assert_called_once_with(2,'provider_unavailable')
            with patch('urllib.request.urlopen',side_effect=AssertionError('cached result')):
                self.assertEqual(provider.complete_text('503 retry'),'재개 성공')

    def test_complete_build_replay_holdout_and_incremental_change(self):
        from backspace_mvp.efficient_teacher import execute
        from backspace_mvp.web import WebStore
        from backspace_mvp.jev import JevProvider
        from backspace_mvp.teacher_reliability import verify_model
        real_validate=JevProvider.validate_response
        class LLM:
            model='fixture-efficient';calls=[]
            def complete(self,prompt,schema,**kwargs):
                self.calls.append(kwargs['stage']);frame=json.loads(prompt.split('\n')[-1])
                if kwargs['stage']=='teacher:bounded_synthesis':
                    return {'hypotheses':[{'dimension':'reasoning_demand','statement':'복제 방향의 비교 설명을 요구한다.',
                        'conditions':['DNA 복제 방향을 설명할 때'],'reasoning_chain':['방향을 비교한다','조건과 결과를 설명한다'],
                        'support_ids':[e['id'] for e in frame[:2]],'counter_ids':[],'alternatives':['단원 공통 요구일 수 있다'],
                        'limitations':['실제 채점 기준 미관찰'],'next_validation_data':['다른 수업의 설명 요구']}]} if len(frame)>1 else {'hypotheses':[]}
                return {'notes':[{'unit':u['id'],'title':'복제 비교','topic':'DNA 복제','content':''.join(p['text'] for p in u['passages']),'uncertainties':[],'in_scope':True} for u in frame],
                    'concepts':[{'label':word,'surface':word,'confidence':.9,'ref':{'evidence_id':frame[0]['passages'][0]['evidence_id']}} for word in ('DNA','프라이머')],
                    'relations':[{'from':'DNA','to':'프라이머','relation':'requires','statement':'DNA 복제는 프라이머가 필요하다.',
                        'conditions':['복제'],'ref':{'evidence_id':frame[0]['passages'][0]['evidence_id']}}],
                    'teacher_cues':[{'dimension':'reasoning_demand','observation':'비교 설명을 요구한다.',
                        'ref':{'evidence_id':frame[0]['passages'][0]['evidence_id']}}]}
        class Judge:
            model='fixture-jev'
            validate_response=staticmethod(real_validate)
            def __init__(self,**kwargs):pass
            def decide(self,state,questions,**kwargs):
                return {'model':self.model,'answers':{q:{'type':'noul','noul':.01 if q.startswith('counter_') else .99} for q in questions}}
        with tempfile.TemporaryDirectory() as d,patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            store=WebStore(storage=Path(d));llm=LLM();llm.calls=[]
            for i in range(2):store.upload(f'DNA 복제에 프라이머가 필요하다. 방향을 비교하고 설명하세요. 자료 {i}'.encode(),'lesson'+str(i)+'.txt','teacher','material')
            with patch('backspace_mvp.llm_provider.create_provider',return_value=llm),patch('backspace_mvp.jev.JevProvider',Judge),patch('backspace_mvp.understanding.open_saved_memory',return_value=MagicMock()):
                first=execute(store,{'id':'first','mode':'workspace'},{},lambda _:None)
                path=store.workspace/'teacher/teacher_model.json';model,flags=verify_model(path)
                self.assertTrue(flags['TEACHER_MODEL_USABLE']);self.assertEqual(first['hypothesis_count'],1)
                original=path.read_bytes();calls=len(llm.calls)
                store.upload(b'EXAM ANSWER MUST NEVER ENTER TEACHER','exam.txt','evaluation','exam','heldout')
                second=execute(store,{'id':'second','mode':'workspace'},{},lambda _:None)
                self.assertTrue(second['cache_reused']);self.assertEqual(len(llm.calls),calls);self.assertEqual(path.read_bytes(),original)
                self.assertNotIn('EXAM ANSWER',original.decode())
                with patch('backspace_mvp.efficient_teacher.SYNTHESIS_VERSION','new-selection-contract'):
                    execute(store,{'id':'synthesis-migration','mode':'workspace'},{},lambda _:None)
                self.assertEqual(llm.calls[calls:],['teacher:bounded_synthesis'])
                calls=len(llm.calls)
                store.upload('DNA 복제는 프라이머를 사용한다. 방향 비교와 조건을 설명하세요.'.encode(),'new.txt','teacher','material')
                execute(store,{'id':'third','mode':'workspace'},{},lambda _:None)
                self.assertEqual(len(llm.calls)-calls,2) # One new source + bounded synthesis, no old-source requests.
                updated,_=verify_model(path);self.assertEqual(len(updated['material_sources']),3)
                self.assertGreater(updated['revision'],model['revision'])
                self.assertTrue((path.parent/'evaluation_snapshots'/(model['content_hash']+'.json')).exists())


if __name__=='__main__':unittest.main()
