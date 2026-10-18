"""Real persistent Chroma + upstream A-MEM; no paid LLM/OCR calls in tests."""
import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backspace_mvp.pipeline import digest,read_source,empty_dataset,ingest
from backspace_mvp.understanding import UnderstandingWorkspace,teacher_memory_context,list_saved_notes,source_fingerprint,parse_note


class FixtureEmbedding:
    def __call__(self,input):
        import numpy as np
        return [np.asarray([float('탈분극' in t or 'Na+' in t),float('감수' in t),float('생태' in t),.01],dtype=np.float32) for t in input]
    def embed_query(self,input):return self(input)
    @staticmethod
    def name():return 'backspace-fixture-embedding'
    def get_config(self):return {}
    def is_legacy(self):return False
    def supported_spaces(self):return ['cosine']
    @staticmethod
    def build_from_config(config):return FixtureEmbedding()


class NoteLLM:
    model='fixture-note';last_model='fixture-note'
    def __init__(self):self.text_calls=0;self.metadata_calls=0
    def complete_text(self,prompt,**kwargs):
        self.text_calls+=1
        frame=json.loads(prompt.split('\n')[-1]);text=frame['text']
        return '제목: 원자료 이해\n주제: 생명과학 / 신경계 / 활동 전위\n\n'+text+'\n제공된 자료 범위의 설명이며 학생의 실제 이해는 관찰되지 않았다.'
    def complete(self,prompt,schema,**kwargs):
        self.metadata_calls+=1
        if 'should_evolve' in schema['properties']:
            ids=re.findall(r'memory id:(un_\w+)',prompt)
            return {'should_evolve':True,'actions':['strengthen','update_neighbor'],
                'suggested_connections':ids,'tags_to_update':['생명과학','신경계'],
                'new_context_neighborhood':['비슷한 원자료가 추가됨']*len(ids),
                'new_tags_neighborhood':[['생명과학','관련 자료'] for _ in ids]}
        return {'keywords':['개념','설명','관계'],'context':'해당 원자료의 의미 이해','tags':['생명과학','신경계','학습자료']}


class AMemTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.llm=NoteLLM()
        self.workspace=UnderstandingWorkspace(self.root/'memory',provider=self.llm,embedding_function=FixtureEmbedding())
        self.addCleanup(self.workspace.system.close)
        self.calls=patch('urllib.request.urlopen',side_effect=AssertionError('No paid API in fixtures'))
        self.calls.start();self.addCleanup(self.calls.stop)

    def source(self,text,name,kind='learning_material'):
        path=self.root/name;path.write_text(text,encoding='utf-8')
        return read_source(path,kind,'fixture_exam' if kind=='exam' else None,perception_dir=self.root/'perception')

    def test_a_multiple_text_notes_topic_and_restart(self):
        source=self.source(('Na+ 통로 개방 → Na+ 유입 → 탈분극.\n'*100),'material.txt')
        original=source['excerpts'][0]['text']
        result=self.workspace.ingest_source(source)
        self.assertGreater(len(result['note_ids']),1)
        for unit in result['units']:
            record=self.workspace.system.records[unit['id']]
            self.assertEqual(original[unit['start']:unit['end']],record['provenance']['quote'])
            self.assertTrue((self.root/'memory/notes'/(unit['id']+'.md')).exists())
        before=self.llm.text_calls
        restarted=UnderstandingWorkspace(self.root/'memory',provider=self.llm,embedding_function=FixtureEmbedding())
        self.addCleanup(restarted.system.close)
        self.assertEqual(restarted.ingest_source(source),result)
        self.assertEqual(before,self.llm.text_calls)
        self.assertEqual(restarted.topic_index()['active_notes'],len(result['note_ids']))

    def test_b_c_semantic_links_evolution_correct_neighbor_and_immutable_content(self):
        from test_semantic_control import TypedFixture
        from backspace_mvp.semantic_control import SemanticControl
        unrelated=self.workspace.ingest_source(self.source('생태계의 구성은 생태 개념으로 설명된다.','other.txt'))['note_ids'][0]
        first=self.workspace.ingest_source(self.source('Na+ 통로 개방으로 Na+가 유입되어 탈분극한다.','first.txt'))['note_ids'][0]
        self.workspace.control=SemanticControl(self.root/'decisions',provider=TypedFixture())
        old_content=self.workspace.system.read(first).content
        untouched=copy.deepcopy(vars(self.workspace.system.read(unrelated)))
        second=self.workspace.ingest_source(self.source('Na+ 유입과 탈분극의 관계를 설명한다.','second.txt'))['note_ids'][0]
        exam=self.workspace.ingest_source(self.source('1. Na+ 통로 개방과 탈분극의 관계를 조건별로 비교하라.','exam.txt','exam'))['note_ids'][0]
        self.assertIn(first,self.workspace.system.read(second).links)
        self.assertIn(second,self.workspace.system.read(first).links)
        self.assertIn(first,self.workspace.system.read(exam).links)
        self.assertEqual(old_content,self.workspace.system.read(first).content)
        self.assertEqual(vars(self.workspace.system.read(unrelated)),untouched)
        self.assertTrue(self.workspace.system.read(first).evolution_history)
        rows=self.workspace.search('Na+ 탈분극',source_type='exam_question')
        self.assertTrue(rows);self.assertEqual(rows[0]['source_type'],'exam_question')
        with self.assertRaises(ValueError):self.workspace.system.update(first,content='changed')

    def test_d_teacher_context_reads_notes_without_llm_or_pdf_and_excludes_stale_sources(self):
        source=self.source('Na+ 유입 → 탈분극.','lesson.txt')
        result=self.workspace.ingest_source(source)
        data=empty_dataset();data['sources']=[source]
        from backspace_mvp import understanding
        def reopen(folder):
            return UnderstandingWorkspace(folder,provider=self.llm,embedding_function=FixtureEmbedding()).system
        with patch.object(understanding,'open_saved_memory',side_effect=reopen):
            context=teacher_memory_context(self.root/'memory',data,'Na+ 탈분극')
            self.assertEqual(context['eligible'],1)
            self.assertEqual(context['notes'][0]['id'],result['note_ids'][0])
            self.assertIn('Na+',context['notes'][0]['content'])
            data['sources'][0]['excerpts'][0]['text']='원문이 변경됨'
            stale=teacher_memory_context(self.root/'memory',data,'Na+')
            self.assertEqual(stale['eligible'],0);self.assertEqual(stale['notes'],[])

    def test_graph_failure_does_not_erase_primary_notes_and_retry_reuses_them(self):
        source=self.source('Na+ 유입 → 탈분극.','material.txt')
        with patch('backspace_mvp.understanding.UnderstandingWorkspace',return_value=self.workspace), \
             patch('backspace_mvp.staged.StagedExtractor.extract',side_effect=ValueError('secondary graph failed')):
            with self.assertRaisesRegex(ValueError,'secondary graph'):
                ingest(self.root/'dataset.json',self.root/'material.txt','learning_material',provider=self.llm,
                    perception_dir=self.root/'perception',memory_workspace=self.root/'memory')
        notes=list_saved_notes(self.root/'memory')
        self.assertEqual(notes['matching_count'],1)
        self.assertFalse((self.root/'dataset.json').exists())
        count=self.llm.text_calls;self.workspace.ingest_source(source)
        self.assertEqual(count,self.llm.text_calls)

    def test_upstream_classes_are_reused(self):
        from backspace_mvp.amem_adapter import BackspaceMemorySystem,BackspaceChromaRetriever
        from backspace_mvp._vendor.amem.memory_system import AgenticMemorySystem
        from backspace_mvp._vendor.amem.retrievers import PersistentChromaRetriever
        self.assertTrue(issubclass(BackspaceMemorySystem,AgenticMemorySystem))
        self.assertIs(BackspaceMemorySystem.process_memory,AgenticMemorySystem.process_memory)
        self.assertIs(BackspaceMemorySystem.analyze_content,AgenticMemorySystem.analyze_content)
        self.assertTrue(issubclass(BackspaceChromaRetriever,PersistentChromaRetriever))
        title,topic,body=parse_note('제목: 신경계\n\n주제: 생명과학 / 신경계\n\nNa+ 유입을 설명한다.','생명과학','원본')
        self.assertEqual(topic,['생명과학','신경계']);self.assertEqual(body,'Na+ 유입을 설명한다.')

    def test_partial_coverage_expands_without_regenerating_completed_note(self):
        source=self.source('Na+ 유입 → 탈분극.','multi.txt')
        source['excerpts']=[{'locator':'p1','text':'Na+ 유입 → 탈분극.'},
            {'locator':'p2','text':'Na+ 통로가 열리는 조건을 비교한다.'}]
        first=self.workspace.ingest_source(source,locators=['p1'])
        self.assertFalse(first['coverage']['complete'])
        full=self.workspace.ingest_source(source)
        self.assertTrue(full['coverage']['complete']);self.assertEqual(len(full['note_ids']),2)
        self.assertIn(first['note_ids'][0],full['note_ids'])
        self.assertEqual(self.llm.text_calls,2)

    def test_rejected_note_is_preserved_but_not_used_in_teacher_or_evolution(self):
        from backspace_mvp.understanding import review_saved_note
        first=self.workspace.ingest_source(self.source('Na+ 유입 → 탈분극.','review.txt'))
        nid=first['note_ids'][0]
        path=self.root/'memory/notes'/(nid+'.md');before=path.read_bytes()
        review_saved_note(self.root/'memory',nid,'rejected','잘못된 표 해석')
        self.workspace.close()
        self.workspace=UnderstandingWorkspace(self.root/'memory',provider=self.llm,embedding_function=FixtureEmbedding())
        self.addCleanup(self.workspace.close)
        self.assertEqual(self.workspace.search('Na+'),[])
        second=self.workspace.ingest_source(self.source('Na+ 통로 개방 → 탈분극.','next.txt'))
        self.assertNotIn(nid,self.workspace.system.read(second['note_ids'][0]).links)
        self.assertEqual(before,path.read_bytes())

    def test_teacher_model_and_plan_keep_existing_chain_with_notes_first(self):
        from test_integration_v07 import seed,LLMFixture,JevFixture
        from backspace_mvp.model import read_json
        from backspace_mvp.patterns import build_patterns
        from backspace_mvp.hypotheses import build_teacher_hypotheses
        from backspace_mvp.scoring import build_teacher_scores
        from backspace_mvp.teacher_model import build_teacher_model
        from backspace_mvp.study_plan import generate_study_plan
        state=seed(self.root);data=read_json(state)
        source=next(s for s in data['sources'] if s['kind']=='learning_material')
        notes=self.workspace.ingest_source(source)
        llm=LLMFixture();original=llm.complete;packets=[]
        def capture(prompt,schema,**kwargs):
            packets.append(json.loads(prompt[prompt.index('{'):]))
            return original(prompt,schema,**kwargs)
        llm.complete=capture
        def reopen(folder):
            return UnderstandingWorkspace(folder,provider=self.llm,embedding_function=FixtureEmbedding()).system
        with patch('backspace_mvp.understanding.open_saved_memory',side_effect=reopen):
            build_patterns(state)
            hypotheses=build_teacher_hypotheses(state,provider=llm,max_hypotheses=1,
                max_patterns=1,max_questions=2,max_material_items=1)
        self.assertEqual(next(iter(packets[0])),'understanding_memory')
        self.assertTrue(hypotheses['understanding_memory']['notes'])
        self.assertEqual(hypotheses['understanding_memory']['notes'][0]['id'],notes['note_ids'][0])
        build_teacher_scores(state,provider=JevFixture(),max_concepts=2,max_hypotheses=1,max_evidence=2)
        model=build_teacher_model(state)
        self.assertEqual(model['actual_student_behavior'],'not_observed')
        plan=generate_study_plan(self.root/'teacher_model.json',state,max_concepts=2,
            days=1,daily_minutes=20,offline=True)
        self.assertTrue(plan['tasks'])


if __name__=='__main__':unittest.main()
