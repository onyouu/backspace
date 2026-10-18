import copy
import json
import tempfile
import unittest
from pathlib import Path
from backspace_mvp.pipeline import save,digest,empty_dataset
from backspace_mvp.model import validate,read_json
from backspace_mvp.understanding import source_fingerprint
from backspace_mvp.teacher_primary import build_primary
from backspace_mvp.source_spans import spans_for,resolve,persist_spans
from backspace_mvp.span_graph import validate_emphasis
from backspace_mvp.staged import StagedExtractor
from backspace_mvp.semantic_control import SemanticControl
from test_teacher_update import TeacherJev


def source(i=1):
    return {'id':f'src_{i}','kind':'learning_material','title':'sample','path':'sample.txt','sha256':digest(i),
        'format':'txt','extraction_status':'text_extracted_needs_review','page_count':1,
        'excerpts':[{'locator':'p1','text':'생태계는 생물적 요소와 비생물적 요소로 구성된다.\n생태계의 구조를 비교하여 설명하시오.'}]}


class SpanProvider:
    source_span_support=True;model='fixture_span'
    def __init__(self,bad=False):self.calls=[];self.bad=bad
    def complete(self,prompt,schema):
        self.calls.append(list(schema['properties'])[0])
        sid=prompt.split('"span_id": "')[1].split('"')[0]
        if 'concepts' in schema['properties']:
            return {'concepts':[{'label':'생태계','evidence_span_ids':[sid],'confidence':.8},
                {'label':'생물적 요소','evidence_span_ids':[sid],'confidence':.8},
                {'label':'잘못된 항목','evidence_span_ids':['S999'],'confidence':.9}]}
        if 'relations' in schema['properties']:
            if self.bad:raise ValueError('invalid_json')
            return {'relations':[]}
        return {'reasoning':[]}


class NotesSpanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'teacher'
        self.data=empty_dataset();save(self.root/'dataset.json',self.data)
        for i in range(1,10):
            s=source(i);nid=f'n_{i}';raw=s['excerpts'][0]['text'];body='관찰 가능한 조건 비교와 설명 요구의 잠정 해석.'
            fingerprint=source_fingerprint(s)
            save(self.root/'pipeline_state/source_snapshots'/f"{s['id']}.json",{'source':s})
            save(self.root/'memory/source_manifests'/f"{s['id']}.json",{'source_id':s['id'],'source_fingerprint':fingerprint,
                'note_ids':[nid],'units':[{'id':nid,'locator':'p1','start':0,'end':len(raw),'text':raw,'content':body}]})
            save(self.root/'memory/notes'/f'{nid}.json',{'id':nid,'content_hash':digest(body),'source_fingerprint':fingerprint,
                'source_type':'learning_material','question_boundary_status':'not_applicable','topic':['biology'],
                'provenance':{'source_id':s['id'],'source_sha256':s['sha256'],'locator':'p1','quote':raw,'span':{'start':0,'end':len(raw)}}})
            (self.root/'memory/notes'/f'{nid}.md').write_text(body,encoding='utf-8')
        self.jev=TeacherJev();self.control=SemanticControl(self.root/'teacher_model/decisions',provider=self.jev)

    def test_a_zero_graph_model_survives(self):
        m=build_primary(self.root/'dataset.json',control=self.control,synthesize=False)
        self.assertEqual(m['status'],'provisional');self.assertEqual(m['coverage']['graph']['completed_count'],0)
        self.assertEqual(m['coverage']['teacher_evidence']['completed'],9)

    def test_b_one_of_nine_graph_model_survives(self):
        self.data['sources']=[source()];save(self.root/'dataset.json',self.data)
        m=build_primary(self.root/'dataset.json',control=self.control,synthesize=False)
        self.assertEqual(m['status'],'provisional');self.assertEqual(m['coverage']['graph']['completed_count'],1)
        self.assertEqual(m['coverage']['graph']['eligible_count'],9)

    def test_c_python_restores_unchanged_text(self):
        s=source();rows=spans_for(s,'p1');self.assertEqual(resolve([rows[0]['span_id']],rows,s)[0]['text'],s['excerpts'][0]['text'])

    def test_d_bad_entry_isolated(self):
        ex=StagedExtractor(SpanProvider(),self.data,source(),self.root/'checkpoints')
        ex.span_control=self.control;value=ex.extract()
        self.assertEqual(len(value['concepts']),2);self.assertTrue(value['sources'][0]['graph_enrichment']['invalid_entry_count'])

    def test_e_explicit_without_spans_rejected(self):
        with self.assertRaisesRegex(ValueError,'missing_source_span'):validate_emphasis({'emphasis_type':'explicit','evidence_span_ids':[]},[],source(),'생태계')

    def test_f_repeated_no_marker_accepted(self):
        s=source();spans=spans_for(s,'p1',max_chars=25)
        validate_emphasis({'emphasis_type':'repeated','evidence_span_ids':[r['span_id'] for r in spans]},spans,s,'생태계')

    def test_g_relation_failure_preserves_cached_concepts(self):
        p=SpanProvider(bad=True);ex=StagedExtractor(p,self.data,source(),self.root/'checkpoints');ex.span_control=self.control
        result=ex.extract();self.assertEqual(len(result['concepts']),2);self.assertGreater(result['sources'][0]['graph_enrichment']['pending_count'],0)
        first=p.calls.count('concepts');p.bad=False
        ex=StagedExtractor(p,self.data,source(),self.root/'checkpoints');ex.span_control=self.control;ex.extract()
        self.assertEqual(first,p.calls.count('concepts'));self.assertEqual(p.calls.count('relations'),2)

    def test_h_later_enrichment_delta_revision_no_generation(self):
        m=build_primary(self.root/'dataset.json',control=self.control,synthesize=False)
        self.data['sources']=[source()];save(self.root/'dataset.json',self.data)
        newer=build_primary(self.root/'dataset.json',control=self.control,synthesize=False)
        self.assertEqual(newer['revision'],m['revision']+1);self.assertEqual(newer['previous_hash'],m['content_hash'])
        same=build_primary(self.root/'dataset.json',control=self.control,synthesize=False)
        self.assertEqual(same['revision'],newer['revision']);self.assertEqual(self.jev.calls,0)

    def test_changed_ocr_supersedes_and_rejects_old_ids(self):
        s=source();old=spans_for(s,'p1');persist_spans(self.root/'spans',s,old)
        changed=copy.deepcopy(s);changed['excerpts'][0]['text']+=' 수정'
        with self.assertRaisesRegex(ValueError,'stale'):resolve([old[0]['span_id']],old,changed)
        persist_spans(self.root/'spans',changed,spans_for(changed,'p1'))
        self.assertEqual(len(list((self.root/'spans/history').glob('*.json'))),1)

    def test_note_candidate_jev_support_without_graph(self):
        self.jev.novel=True
        class Generator:
            def complete(self,prompt,schema):
                ids=schema['properties']['hypotheses']['items']['properties']['evidence_ids']['items']['enum']
                return {'hypotheses':[{'statement':'이 자료에서는 조건 비교 뒤 설명을 요구하는 경향이 있다.',
                    'conditions':['제공된 비교 설명 자료 범위'],'evidence_ids':ids,'alternatives':['일반적인 교과 구성'],
                    'limitations':['시험 문항과 실제 수행 미관찰']}]}
        m=build_primary(self.root/'dataset.json',control=self.control,provider=Generator())
        self.assertEqual(m['status'],'usable');self.assertEqual(len(m['assessment_ideals']),1)
        self.assertEqual(m['assessment_ideals'][0]['graph_support'],'pending')
        self.assertEqual(m['assessment_ideals'][0]['incremental_state']['statistics']['independent_questions'],0)

    def test_invalid_optional_graph_does_not_block_primary(self):
        save(self.root/'dataset.json',{'broken':'optional graph'})
        m=build_primary(self.root/'dataset.json',control=self.control,synthesize=False)
        self.assertEqual(m['status'],'provisional');self.assertTrue(m['optional_errors'])

    def test_multiple_span_refs_in_one_observation(self):
        from backspace_mvp.source_spans import reference
        s=source();spans=spans_for(s,'p1',max_chars=25);cid='eco'
        data={**self.data,'sources':[s],'concepts':[{'id':cid,'label':'생태계','aliases':[]}],
            'material_observations':[{'id':'mo_'+digest([s['id'],'p1',cid])[:20],'concept_id':cid,
                'surface_form':'생태계','confidence':.8,'evidence':[reference(r) for r in spans],
                'explicit_emphasis':[],'grounding_method':'source_span','emphasis_classifications':[]}]}
        validate(data)

    def test_question_wire_has_no_quote_and_is_restored(self):
        from backspace_mvp.span_question import QuestionSpanCall
        from backspace_mvp.contracts import obj,TEXT,CONFIDENCE,REFS
        s=source();text=s['excerpts'][0]['text']
        schema=obj({'task':obj({'description':TEXT,'quote':TEXT,'confidence':CONFIDENCE}),
            'claims':{'type':'array','items':obj({'references':REFS})},
            'steps':{'type':'array','items':obj({'criterion_references':REFS})}})
        class Provider:
            model='span_fixture'
            def complete(_,prompt,contract):
                self.assertNotIn('quote',contract['properties']['task']['properties'])
                sid=prompt.split('"span_id": "')[1].split('"')[0]
                return {'task':{'description':'조건 비교','evidence_span_ids':[sid],'confidence':.8},
                    'claims':[{'references':[{'span_id':sid},{'span_id':'S999'}]}],'steps':[{'criterion_references':[]}]}
        ex=StagedExtractor(Provider(),self.data,s,self.root/'checkpoints')
        call=QuestionSpanCall(ex,'p1',{'text':text,'context':''},{})
        result=call('question','자료는 데이터',schema,600,lambda v:None)
        self.assertEqual(result['task']['quote'],text);self.assertEqual(len(result['claims'][0]['references']),1)
        self.assertEqual(len(ex.manifest['invalid_span_entries']),1)

    def test_question_segmentation_uses_span_ids(self):
        from backspace_mvp.span_question import segment_question_spans
        s=source();s['excerpts'][0]['text']='1. 조건을 비교하시오.\n근거를 제시하시오.'
        class Provider:
            model='segment_fixture'
            def complete(_,prompt,contract):
                rows=json.loads(prompt.split('\n',1)[1])['spans']
                return {'questions':[{'number':'1','start_span_id':rows[0]['span_id'],'end_span_id':rows[-1]['span_id'],
                    'context_span_ids':[],'complete':True}]}
        ex=StagedExtractor(Provider(),self.data,s,self.root/'checkpoints')
        result=segment_question_spans(ex,s['excerpts'][0],lambda v:None)
        self.assertEqual(result['questions'][0]['text'],s['excerpts'][0]['text'])

    def test_current_ocr_edit_invalidates_old_primary(self):
        from backspace_mvp.teacher_primary import collect
        save(self.root.parent/'files.json',[{'target':'teacher','pipeline_source_id':'src_1',
            'sha256':source()['sha256'],'perception_hash':'new_transcription_version','visual_pages':{}}])
        self.addCleanup(lambda:(self.root.parent/'files.json').unlink(missing_ok=True))
        sources,records,eligible,rejected,_=collect(self.root)
        self.assertEqual(records,{});self.assertEqual(rejected[0]['reason'],'current_transcription_changed')
