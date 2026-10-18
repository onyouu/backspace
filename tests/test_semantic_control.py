"""Typed routing A–G plus failure, provenance, replay and output regression."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backspace_mvp.jev import JevProvider
from backspace_mvp.semantic_control import SemanticControl,thresholds
from backspace_mvp.jev_questions import hypothesis_questions,note_questions
from backspace_mvp.pipeline import empty_dataset,read_source,digest
from backspace_mvp.understanding import UnderstandingWorkspace
from backspace_mvp.staged import StagedExtractor
from backspace_mvp.nvidia import SemanticReductionRequired
from test_amem import FixtureEmbedding,NoteLLM
from test_integration_v07 import seed,LLMFixture,JevFixture


class TypedFixture:
    model='jev-typed-fixture'
    def __init__(self, *, relation='reinforces', slow=.01, graph=.01, fail=False):
        self.calls=[];self.relation=relation;self.slow=slow;self.graph=graph;self.fail=fail
        self.hyp_relation='supports';self.confidence=.95
    def decide(self,state,questions,**kwargs):
        self.calls.append((copy.deepcopy(state),copy.deepcopy(questions)))
        if self.fail:raise ValueError('simulated unavailable')
        answers={}
        for q,contract in questions.items():
            kind=contract['type']
            if kind=='noul':
                p=self.graph if q.startswith('graph_') else self.slow if q=='needs_slow_reasoning' else .99 if q=='duplicate' else .01
                answers[q]={'type':kind,'noul':p}
            elif kind=='choice':
                options=contract['criteria']
                option=(('topic_0' if 'topic_0' in options else 'new_topic') if q=='topic' else
                    self.relation if q=='relation' and 'new_note' in state else self.hyp_relation if q=='relation' else
                    'question_type_specific' if q=='scope' else 'local_adjustment')
                answers[q]={'type':kind,'choice':option,'confidence':self.confidence,
                    'probabilities':{o:float(o==option) for o in options}}
            else:
                levels=contract['criteria']
                answers[q]={'type':kind,'score':3,'confidence':self.confidence,
                    'probabilities':{str(i):float(i==3) for i in range(len(levels))},
                    'legend':{str(i):level for i,level in enumerate(levels)}}
        return {'model':self.model,'answers':answers,'usage':{'input_tokens':100,'output_tokens':0}}


class SemanticControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.jev=TypedFixture()
        self.control=SemanticControl(self.root/'jev_decisions',provider=self.jev)
        self.metadata={'id':'new','title':'활동 전위','topic':['생명과학','신경계'],
            'source_type':'learning_material','source_fingerprint':'version',
            'provenance':{'source_id':'s_new','source_fingerprint':'version','locator':'page:1','quote':'Na+ 유입 → 탈분극'}}
        self.related=[{'id':'old','content':'Na+ 유입으로 탈분극한다.','topic':['생명과학','신경계'],
            'source_type':'learning_material','provenance':{'source_id':'s_old','quote':'Na+ 유입 → 탈분극'},
            'amem':{'keywords':['Na+','탈분극'],'context':'Na+ 유입','tags':['신경계']}}]
    def route(self):return self.control.route_note('Na+ 유입 → 탈분극',self.metadata,self.related)
    def workspace(self,control=None):
        llm=NoteLLM();workspace=UnderstandingWorkspace(self.root/'memory',provider=llm,
            embedding_function=FixtureEmbedding(),control=control)
        self.addCleanup(workspace.close);return workspace,llm
    def source(self,text,name):
        path=self.root/name;path.write_text(text,encoding='utf-8')
        return read_source(path,'learning_material',perception_dir=self.root/'perception')

    def test_a_repeated_note_adds_no_metadata_or_evolution_llm_call(self):
        workspace,llm=self.workspace()
        first=workspace.ingest_source(self.source('Na+ 유입으로 탈분극한다.','first.txt'))
        before=llm.metadata_calls
        workspace.control=self.control;workspace.control_version='fixture-control'
        second_text='자료 2: Na+ 유입으로 탈분극한다.'
        second=workspace.ingest_source(self.source(second_text,'second.txt'))
        self.assertEqual(llm.metadata_calls,before)
        self.assertEqual(len(self.jev.calls),1)
        self.assertEqual(len(self.jev.calls[0][1]),9)
        nid=second['note_ids'][0];self.assertIn(first['note_ids'][0],workspace.system.read(nid).links)
        self.assertNotEqual(nid,first['note_ids'][0])
        self.assertEqual(workspace.system.records[nid]['provenance']['source_id'],second['source_id'])
        calls=(llm.text_calls,llm.metadata_calls,len(self.jev.calls))
        self.assertEqual(workspace.ingest_source(self.source(second_text,'second.txt')),second)
        self.assertEqual(calls,(llm.text_calls,llm.metadata_calls,len(self.jev.calls)))

    def test_b_new_explanation_retains_slow_reasoning(self):
        workspace,llm=self.workspace();workspace.ingest_source(self.source('Na+ 유입 → 탈분극','first.txt'))
        before=llm.metadata_calls
        self.jev.relation='extends';self.jev.slow=.99;self.jev.graph=.99
        workspace.control=self.control
        result=workspace.ingest_source(self.source('조건을 바꿔 Na+ 유입과 탈분극을 비교한다.','second.txt'))
        self.assertEqual(llm.metadata_calls,before)
        self.assertTrue(result['units'][0]['semantic_control']['final_route']['needs_slow_reasoning'])

    def test_c_contradiction_overrides_false_slow_gate(self):
        self.jev.relation='contradicts'
        route=self.route()['final_route']
        self.assertTrue(route['needs_slow_reasoning']);self.assertTrue(route['project_graph'])

    def test_d_generic_note_kept_without_graph_calls_or_invented_counts(self):
        source=self.source('Na+ 용어를 확인한다.','generic.txt')
        decision=self.route()
        unit={'id':'new','content':'용어 목록','content_hash':digest('용어 목록'),'text':source['excerpts'][0]['text'],
            'locator':source['excerpts'][0]['locator'],'start':0,'end':len(source['excerpts'][0]['text']),
            'semantic_control':decision}
        extractor=StagedExtractor(NoteLLM(),empty_dataset(),source,self.root/'checkpoints',understanding_units=[unit])
        with patch.object(extractor,'material',side_effect=AssertionError('Must not project')):
            result=extractor.extract()
        self.assertEqual(result['material_observations'],[])
        self.assertEqual(result['sources'][0]['graph_projection']['notes_only'],1)
        self.assertEqual(result['sources'][0]['excerpts'],source['excerpts'])
        from backspace_mvp.materials import export_material_graph
        graph=export_material_graph(result,self.root/'material_graph.json')
        self.assertEqual(graph['sources'][0]['graph_projection']['notes_only'],1)
        from backspace_mvp.model import validate
        broken=copy.deepcopy(result);broken['sources'][0]['graph_projection']['notes_only']=0
        with self.assertRaisesRegex(ValueError,'coverage/counts'):validate(broken)
        self.assertEqual(len(self.jev.calls),1)
        self.assertTrue(list((self.root/'jev_decisions/graph_gate').glob('*.json')))

    def hypothesis(self):
        return {'id':'h1','statement':'제공된 두 문항은 조건 비교를 요구한다.',
                'applicable_context':{'conditions':['두 문항']},'structural_statistics':[]}
    def test_e_support_scope_and_strength_remain_separate(self):
        value=self.control.validate_hypothesis(self.hypothesis(),[{'question_id':'q1'},{'question_id':'q2'}])
        self.assertEqual(value['summary_status'],'supports');self.assertEqual(value['strength_score'],3)
        self.assertEqual(value['scope'],'question_type_specific');self.assertNotIn('confidence',value)
        record=json.loads(next((self.root/'jev_decisions/hypothesis_validation').glob('*.json')).read_text(encoding='utf-8'))
        self.assertIsNone(record['confidence']['reanalysis']);self.assertEqual(record['probabilities']['reanalysis'],.01)

    def test_f_irrelevant_is_never_rewritten_as_contradiction(self):
        self.jev.hyp_relation='irrelevant'
        value=self.control.validate_hypothesis(self.hypothesis(),[{'text':'무관한 사실'}])
        self.assertEqual(value['summary_status'],'irrelevant')
        self.assertEqual(value['evidence_relation'],'irrelevant')

    def test_g_failure_keeps_information_and_legacy_calls(self):
        self.jev.fail=True
        workspace,llm=self.workspace();workspace.control=self.control
        source=self.source('Na+ 유입 → 탈분극','lesson.txt')
        result=workspace.ingest_source(source)
        self.assertEqual(llm.metadata_calls,0)
        decision=result['units'][0]['semantic_control']
        self.assertEqual(decision['status'],'fallback')
        self.assertTrue(decision['final_route']['needs_slow_reasoning']);self.assertTrue(decision['final_route']['project_graph'])
        self.assertEqual(workspace.system.records[result['note_ids'][0]]['provenance']['quote'],source['excerpts'][0]['text'])

    def test_borderline_and_low_confidence_are_unknown_not_false(self):
        self.jev.slow=.5;self.jev.graph=.5;self.jev.confidence=.1
        value=self.route();self.assertTrue(value['final_route']['needs_slow_reasoning'])
        self.assertTrue(value['final_route']['project_graph']);self.assertIsNone(value['final_route']['relation'])
        self.assertIsNone(value['confidence']['duplicate'])

    def test_success_cache_and_config_model_question_invalidation(self):
        self.route();self.route();self.assertEqual(len(self.jev.calls),1)
        self.control.threshold_version+='changed';self.route();self.assertEqual(len(self.jev.calls),2)
        self.jev.model='different-model';self.route();self.assertEqual(len(self.jev.calls),3)
        with patch('backspace_mvp.semantic_control.NOTE_VERSION','wording-2'):
            self.route()
        self.assertEqual(len(self.jev.calls),4)

    def test_failure_is_audited_but_retried_not_cached_as_false(self):
        self.jev.fail=True;self.route();self.route();self.assertEqual(len(self.jev.calls),2)
        self.jev.fail=False;self.assertEqual(self.route()['status'],'success')

    def test_invalid_probability_boolean_and_answer_ids_rejected(self):
        qs=note_questions([]);raw=self.jev.decide({'new_note':{}},qs)
        raw['answers']['duplicate']['noul']=True
        with self.assertRaises(ValueError):JevProvider.validate_response(raw,qs)
        raw['answers'].pop('duplicate')
        with self.assertRaises(ValueError):JevProvider.validate_response(raw,qs)

    def test_hypothesis_validation_survives_full_teacher_and_plan_chain(self):
        from backspace_mvp.patterns import build_patterns
        from backspace_mvp.hypotheses import build_teacher_hypotheses
        from backspace_mvp.scoring import build_teacher_scores
        from backspace_mvp.teacher_model import build_teacher_model
        from backspace_mvp.study_plan import generate_study_plan
        state=seed(self.root);build_patterns(state)
        llm=LLMFixture()
        hypotheses=build_teacher_hypotheses(state,provider=llm,control=self.control,max_hypotheses=1,
            max_patterns=1,max_questions=2,max_material_items=1)
        self.assertEqual(hypotheses['hypotheses'][0]['jev_validation']['summary_status'],'supports')
        before=(llm.calls,len(self.jev.calls))
        self.assertEqual(hypotheses,build_teacher_hypotheses(state,provider=llm,control=self.control,
            max_hypotheses=1,max_patterns=1,max_questions=2,max_material_items=1))
        self.assertEqual(before,(llm.calls,len(self.jev.calls)))
        build_teacher_scores(state,provider=JevFixture(),max_concepts=2,max_hypotheses=1,max_evidence=2)
        model=build_teacher_model(state)
        self.assertEqual(model['assessment_ideals'][0]['jev_validation'],hypotheses['hypotheses'][0]['jev_validation'])
        plan=generate_study_plan(self.root/'teacher_model.json',state,max_concepts=2,days=1,daily_minutes=20,offline=True)
        self.assertEqual(plan['budget']['scheduled_minutes'],20)
        self.assertEqual(model['actual_student_behavior'],'not_observed')

    def test_understanding_timeout_splits_and_resume_never_retries_large_unit(self):
        workspace,llm=self.workspace();original=llm.complete_text;lengths=[]
        def bounded(prompt,**kwargs):
            text=json.loads(prompt.split('\n')[-1])['text'];lengths.append(len(text))
            if len(text)>500:raise SemanticReductionRequired('timeout',stage='understanding',reason='timeout')
            return original(prompt,**kwargs)
        llm.complete_text=bounded
        source=self.source(('Na+ 유입 → 탈분극.\n'*70),'large.txt')
        first=workspace.ingest_source(source)
        self.assertGreater(len(first['note_ids']),1)
        calls=len(lengths);workspace.ingest_source(source);self.assertEqual(len(lengths),calls)
        for unit in first['units']:
            self.assertEqual(source['excerpts'][0]['text'][unit['start']:unit['end']],unit['text'])
        self.assertTrue(list((self.root/'memory/content_checkpoints').glob('*.reduction.json')))

    def test_graph_timeout_reduces_and_restart_avoids_large_prompt(self):
        source=self.source('Na+ 유입 → 탈분극.\n'*70,'graph.txt');lengths=[]
        def extraction(ex,page):
            lengths.append(len(page['text']))
            if len(page['text'])>500:raise SemanticReductionRequired('limit',stage='material',reason='output_limit')
            return []
        with patch('backspace_mvp.grounded.extract_material',side_effect=extraction):
            for _ in range(2):
                extractor=StagedExtractor(NoteLLM(),empty_dataset(),source,self.root/'checkpoints')
                extractor.extract()
        self.assertEqual(sum(n>500 for n in lengths),1)
        self.assertTrue(list((self.root/'checkpoints'/source['id']).glob('*.reduction.json')))

    def test_metadata_timeout_keeps_note_and_marks_deferred_interpretation(self):
        workspace,llm=self.workspace()
        def slow(*args,**kwargs):
            raise SemanticReductionRequired('timeout',stage='amem:metadata',reason='timeout')
        llm.complete=slow
        source=self.source('Na+ 유입 → 탈분극','metadata.txt')
        result=workspace.ingest_source(source)
        nid=result['note_ids'][0]
        self.assertEqual(workspace.system.records[nid]['metadata_status'],'local_title_topic')
        self.assertEqual(workspace.system.read(nid).content,result['units'][0]['content'])
        self.assertEqual(llm.metadata_calls,0)
        with patch.object(llm,'complete',side_effect=AssertionError('No unchanged retry')):
            self.assertEqual(workspace.ingest_source(source),result)

    def test_metadata_network_error_keeps_existing_body_with_local_metadata(self):
        workspace,llm=self.workspace()
        llm.complete=lambda *a,**k: (_ for _ in ()).throw(OSError('metadata connection unavailable'))
        result=workspace.ingest_source(self.source('Na+ 유입 → 탈분극','metadata-network.txt'))
        nid=result['note_ids'][0]
        self.assertEqual(workspace.system.records[nid]['metadata_status'],'local_title_topic')
        self.assertEqual(workspace.system.read(nid).content,result['units'][0]['content'])

    def test_hypothesis_timeout_selects_fewer_complete_cards_and_reuses_reduction(self):
        from backspace_mvp.patterns import build_patterns
        from backspace_mvp.hypotheses import build_teacher_hypotheses
        state=seed(self.root);build_patterns(state)
        llm=LLMFixture();original=llm.complete;prompts=[]
        def slow_first(prompt,schema,**kwargs):
            prompts.append(prompt)
            if len(prompts)==1:raise SemanticReductionRequired('limit',stage='teacher_hypotheses',reason='output_limit')
            return original(prompt,schema,**kwargs)
        llm.complete=slow_first
        result=build_teacher_hypotheses(state,provider=llm,control=self.control,max_hypotheses=4,
            max_patterns=8,max_questions=8,max_material_items=4)
        self.assertEqual(len(prompts),2);self.assertLess(len(prompts[1]),len(prompts[0]))
        self.assertGreaterEqual(len(result['hypotheses'][0]['supporting_question_ids']),2)
        self.assertEqual(result,build_teacher_hypotheses(state,provider=llm,control=self.control,max_hypotheses=4,
            max_patterns=8,max_questions=8,max_material_items=4))
        self.assertEqual(len(prompts),2)


if __name__=='__main__':unittest.main()
