"""Commit boundary and resumable orchestration: injected faults, no paid calls."""
import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backspace_mvp.model import read_json
from backspace_mvp.pipeline import digest, empty_dataset, read_source
from backspace_mvp.stage_state import StageLedger, outcome
from backspace_mvp.understanding import UnderstandingWorkspace, list_saved_notes
from backspace_mvp.web import WebStore
from test_amem import NoteLLM
from test_semantic_control import TypedFixture
from backspace_mvp.semantic_control import SemanticControl


class LocalMemory:
    def __init__(self,folder):self.folder=folder;self.records={};self.fail=False
    def attach_committed(self,content,metadata):
        # Proves canonical commit happens before optional enrichment.
        path=self.folder/'notes'/(metadata['id']+'.json')
        assert path.exists() and path.with_suffix('.md').exists()
        if self.fail:raise ConnectionError('metadata index unavailable')
        self.records[metadata['id']]=copy.deepcopy(metadata)
    def related_for_control(self,*args):return []
    def close(self):pass


class StagePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.llm=NoteLLM()
        block=patch('urllib.request.urlopen',side_effect=AssertionError('No paid API in stage tests'))
        block.start();self.addCleanup(block.stop)
    def source(self,text='조건과 관계를 설명한다.',name='lesson.txt'):
        p=self.root/name;p.write_text(text,encoding='utf-8')
        return read_source(p,'learning_material',perception_dir=self.root/'perception')
    def workspace(self,control=None):
        memory=LocalMemory(self.root/'memory')
        return UnderstandingWorkspace(self.root/'memory',provider=self.llm,system=memory,control=control),memory
    def test_a_metadata_failure_is_partial_and_commit_is_preserved(self):
        workspace,memory=self.workspace();memory.fail=True
        result=workspace.ingest_source(self.source())
        self.assertEqual(result['outcome'],'partial_success')
        self.assertEqual(list_saved_notes(self.root/'memory')['matching_count'],1)
        rows=workspace.ledger.rows()
        self.assertTrue(any(r['stage']=='MEMORY_ENRICHMENT' and r['status']=='failed_retryable' for r in rows))
        self.assertTrue(any(r['stage']=='UNDERSTANDING' and r['status']=='complete' for r in rows))
    def test_b_jev_failure_is_pending_and_reuses_stored_note(self):
        jev=TypedFixture(fail=True);control=SemanticControl(self.root/'jev',provider=jev)
        workspace,memory=self.workspace(control)
        source=self.source();first=workspace.ingest_source(source)
        self.assertEqual(first['outcome'],'partial_success')
        self.assertTrue(any(r['stage']=='JEV_ROUTING' and r['status']=='failed_retryable' for r in workspace.ledger.rows()))
        before=self.llm.text_calls;jev.fail=False
        workspace.ingest_source(source,downstream_only=True)
        self.assertEqual(before,self.llm.text_calls)
        self.assertEqual(list_saved_notes(self.root/'memory')['matching_count'],1)
    def test_understanding_failures_are_per_unit_and_coverage_is_honest(self):
        workspace,_=self.workspace();source=self.source()
        source['excerpts']=[{'locator':'p1','text':'조건 관계를 설명한다.'},{'locator':'p2','text':'깨진 원문'}]
        original=self.llm.complete_text
        self.llm.complete_text=lambda prompt,**kw: (_ for _ in ()).throw(ConnectionError('network_error')) if '깨진 원문' in prompt else original(prompt,**kw)
        result=workspace.ingest_source(source)
        self.assertFalse(result['coverage']['complete']);self.assertEqual(len(result['units']),1)
        self.assertEqual(result['outcome'],'partial_success')
    def test_no_note_means_failed_before_understanding(self):
        workspace,_=self.workspace()
        self.llm.complete_text=lambda *a,**k:(_ for _ in ()).throw(ConnectionError('network_error'))
        result=workspace.ingest_source(self.source())
        self.assertEqual(result['outcome'],'failed_before_understanding')
        self.assertEqual(result['note_ids'],[])
    def test_g_replay_has_no_duplicate_note_or_completed_stage_attempt(self):
        workspace,_=self.workspace();source=self.source()
        workspace.ingest_source(source);counts={r['task_id']:r['attempt_count'] for r in workspace.ledger.rows()}
        workspace.ingest_source(source)
        self.assertEqual(counts,{r['task_id']:r['attempt_count'] for r in workspace.ledger.rows()})
        self.assertEqual(self.llm.text_calls,1)
    def test_missing_index_does_not_block_understanding(self):
        workspace=UnderstandingWorkspace(self.root/'memory',provider=self.llm)
        with patch('backspace_mvp.amem_adapter.BackspaceMemorySystem',side_effect=RuntimeError('index initialization failed')):
            result=workspace.ingest_source(self.source())
        self.assertEqual(result['outcome'],'partial_success')
        self.assertTrue((self.root/'memory/notes'/(result['note_ids'][0]+'.md')).exists())
    def test_stage_diagnostics_and_restart_preserve_attempt_count(self):
        ledger=StageLedger(self.root/'stages');task=ledger.ensure('GRAPH_PROJECTION','s','hash',checkpoint='checkpoint.json')
        ledger.set(ledger.ensure('UNDERSTANDING','s','hash'),'complete')
        ledger.run(task,lambda:(_ for _ in ()).throw(TimeoutError('timeout')),input_size=1234)
        restored=StageLedger(self.root/'stages').pending()[0]
        self.assertEqual(restored['attempt_count'],1)
        self.assertEqual(restored['last_error']['error_type'],'timeout')
        self.assertEqual(read_json(restored['diagnostic'])['input_size'],1234)
        ledger.run(restored,lambda:42);self.assertEqual(restored['attempt_count'],2)
        ledger.run(restored,lambda:(_ for _ in ()).throw(AssertionError('completed task')))
        self.assertEqual(restored['attempt_count'],2)
    def test_rejected_is_needs_review(self):
        self.assertEqual(outcome([{'stage':'UNDERSTANDING','status':'rejected'}]),'needs_review')


class WebStageTests(StagePipelineTests):
    def setup_web(self,number=1):
        store=WebStore(storage=self.root/'web')
        for i in range(number):store.upload(('조건 관계 '+str(i)).encode(),'file'+str(i)+'.txt','teacher','material')
        return store
    def patches(self,fail_sources=()):
        from backspace_mvp.staged import StagedExtractor
        def extract(extractor):
            if extractor.source['title'] in fail_sources:raise TimeoutError('graph timeout')
            value=empty_dataset();value['sources']=[extractor.source];return value
        def workspace(folder,**kw):return UnderstandingWorkspace(folder,provider=self.llm,system=LocalMemory(folder))
        return (patch('backspace_mvp.llm_provider.create_provider',return_value=self.llm),
                patch('backspace_mvp.understanding.UnderstandingWorkspace',side_effect=workspace),
                patch.object(StagedExtractor,'extract',extract),
                patch('backspace_mvp.teacher_incremental.update_teacher_model',return_value={'incremental':{}}))
    def run_job(self,store,action,**opts):
        job=store.start(action,{'mode':'workspace',**opts});deadline=time.monotonic()+12
        while store.active and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNone(store.active);return store.jobs[job['id']]
    def test_c_graph_timeout_preserves_usable_teacher_note_evidence(self):
        store=self.setup_web()
        p=self.patches(['file0.txt'])
        with p[0],p[1],p[2],p[3]:result=self.run_job(store,'teacher')
        self.assertEqual(result['status'],'done');self.assertEqual(result['outcome'],'partial_success')
        state=read_json(store.workspace/'teacher/teacher_model/state.json')
        self.assertEqual(len(state['evidence']),1)
        self.assertEqual(next(iter(state['evidence'].values()))['record']['kind'],'understanding_note')
        self.assertEqual(list_saved_notes(store.workspace/'teacher/memory')['matching_count'],1)
    def test_d_nine_files_seven_complete_two_graph_pending(self):
        store=self.setup_web(9);p=self.patches(['file7.txt','file8.txt'])
        with p[0],p[1],p[2],p[3]:result=self.run_job(store,'teacher')
        self.assertEqual(result['outcome'],'partial_success');self.assertEqual(result.get('stored_notes'),9,result)
        rows=store.files();self.assertEqual(sum(r['status']=='analyzed' for r in rows),7)
        pending=StageLedger(store.workspace/'teacher/pipeline_state').pending()
        self.assertEqual(sum(t['stage']=='GRAPH_PROJECTION' for t in pending),2)
    def test_e_one_understanding_failure_does_not_stop_other_files(self):
        store=self.setup_web(2);original=self.llm.complete_text
        self.llm.complete_text=lambda prompt,**kw:(_ for _ in ()).throw(ConnectionError('network_error')) if '조건 관계 0' in prompt else original(prompt,**kw)
        p=self.patches()
        with p[0],p[1],p[2],p[3]:result=self.run_job(store,'teacher')
        self.assertEqual(result['outcome'],'partial_success')
        self.assertEqual(store.files()[0]['pipeline_outcome'],'failed_before_understanding')
        self.assertEqual(store.files()[1]['understanding_notes'],1)
    def test_f_resume_graph_never_replays_perception_or_understanding(self):
        store=self.setup_web();p=self.patches(['file0.txt'])
        with p[0],p[1],p[2],p[3]:self.run_job(store,'teacher')
        calls=self.llm.text_calls;p=self.patches()
        with p[0],p[1],p[2],p[3],patch('backspace_mvp.web_pipeline.read_source',side_effect=AssertionError('No perception replay')):
            result=self.run_job(store,'resume',target='teacher')
        self.assertEqual(result['outcome'],'complete',result.get('stage_tasks'))
        self.assertEqual(self.llm.text_calls,calls)
        self.assertEqual(len(read_json(store.workspace/'teacher/dataset.json')['sources']),1)
        before=digest(read_json(store.workspace/'teacher/teacher_model/state.json'))
        with p[0],p[1],p[2],p[3]:self.run_job(store,'resume',target='teacher')
        self.assertEqual(before,digest(read_json(store.workspace/'teacher/teacher_model/state.json')))
    def test_stale_snapshot_rejected_without_api(self):
        store=self.setup_web();p=self.patches(['file0.txt'])
        with p[0],p[1],p[2],p[3]:self.run_job(store,'teacher')
        files=store.files();files[0]['perception_hash']='changed'
        from backspace_mvp.pipeline import save
        save(store.workspace/'files.json',files)
        with patch('backspace_mvp.llm_provider.create_provider',side_effect=AssertionError('No stale API')):
            result=self.run_job(store,'resume',target='teacher')
        self.assertTrue(any(t['status']=='failed_terminal' for t in result['stage_tasks']))


if __name__=='__main__':unittest.main()
