import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from backspace_mvp.visual import analyze_page, read_report, attach_reports, validate_result, VISUAL
from backspace_mvp.perception import extract_document, review_document, source_from_document
from backspace_mvp.nvidia import NvidiaProvider
from backspace_mvp.pipeline import empty_dataset, digest
from backspace_mvp.model import validate, read_json
from backspace_mvp.staged import StagedExtractor


class Reader:
    def recognize(self, image):
        return [{'text':text, 'confidence':.99, 'polygon':[[10,y],[100,y],[100,y+15],[10,y+15]]}
                for text,y in [('ATP',10),('산소',50)]]


RESULT = {'summary':'ATP 표기가 보인다.',
          'observations':[{'description':'ATP라는 글자가 상단에 있다.','image_id':'placeholder',
                           'region':[0,0,1,1],'confidence':.8}],
          'connections':[], 'uncertainties':['화살표 관계는 확인할 수 없다.']}


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'page.png';Image.new('RGB',(320,200),'white').save(self.path)
        self.doc,self.manifest=extract_document(self.path,self.root/'perception',reader=Reader())

    def provider(self):
        class Fixture:
            model='fixture-vision';last_model=None;image_inputs=[];calls=0
            def complete(this,prompt,schema,**kwargs):
                this.calls+=1
                result=copy.deepcopy(RESULT)
                result['observations'][0]['image_id']=this.image_inputs[0]['id']
                return result
        return Fixture()

    def test_cache_invalidation_original_preservation_and_asset_integrity(self):
        provider=self.provider();before=self.manifest.read_bytes();original=self.path.read_bytes()
        report=analyze_page(self.path,self.manifest,'p1',provider)
        self.assertEqual(provider.calls,1)
        self.assertEqual(analyze_page(self.path,self.manifest,'p1',provider),report)
        self.assertEqual(provider.calls,1)
        self.assertEqual(before,self.manifest.read_bytes());self.assertEqual(original,self.path.read_bytes())
        source=attach_reports(source_from_document(self.path,self.doc,'learning_material'),self.doc,self.manifest)
        data=empty_dataset();data['sources']=[source];validate(data)
        data['sources'][0]['visual_context']['p1']['result']['summary']='tampered'
        with self.assertRaisesRegex(ValueError,'provenance'):validate(data)
        edited=review_document(self.manifest,1,self.doc['pages'][0]['blocks'][0]['id'],'ATP 생성')
        self.assertIsNone(read_report(self.manifest,edited,'p1'))
        analyze_page(self.path,self.manifest,'p1',provider)
        self.assertEqual(provider.calls,2)
        self.assertTrue(list((self.manifest.parent/'visual_history').glob('*.json')))

    def test_unknown_image_and_invalid_coordinates_rejected(self):
        for key,value in [('image_id','invented'),('region',[.8,0,.1,1])]:
            result=copy.deepcopy(RESULT);result['observations'][0][key]=value
            with self.assertRaises(ValueError):validate_result(result,[{'id':'placeholder'}])

    def test_nvidia_transmits_images_without_logging_image_or_key(self):
        report=analyze_page(self.path,self.manifest,'p1',self.provider())
        with patch.dict(os.environ,{'NVIDIA_API_KEY':'secret-fixture-key','NVIDIA_LOG_DIR':str(self.root/'logs')},clear=True):
            provider=NvidiaProvider(env_file=self.root/'missing.env',task='vision')
            provider.image_inputs=[{'id':i['id'],'path':self.manifest.parent/i['file']} for i in report['images']]
            response=io.BytesIO(('data: '+json.dumps({'choices':[{'delta':{'content':'{"ok":true}'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n').encode())
            with patch('urllib.request.urlopen',return_value=response) as request:
                self.assertEqual(provider.complete('look',{'type':'object'},max_tokens=1024),{'ok':True})
            payload=json.loads(request.call_args.args[0].data)
            self.assertEqual(payload['model'],NvidiaProvider.VISION)
            self.assertTrue(payload['stream'])
            self.assertEqual(provider.fallback,provider.model)
            self.assertTrue(payload['messages'][1]['content'][-1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
            log=provider.log_path.read_text();self.assertNotIn('base64',log);self.assertNotIn('secret-fixture-key',log)

    def test_material_extraction_and_review_receive_original_images(self):
        report=analyze_page(self.path,self.manifest,'p1',self.provider())
        inputs={};source=attach_reports(source_from_document(self.path,self.doc,'learning_material'),self.doc,self.manifest,inputs)
        seen=[]
        def complete(provider,prompt,schema,**kwargs):
            seen.append((kwargs['stage'],bool(provider.image_inputs)))
            if 'verdicts' in schema['properties']:
                return {'verdicts':[{'index':0,'status':'supported','reason':'합성 연결 검수'}]}
            if 'reasoning' in schema['properties']:return {'reasoning':[]}
            sid=prompt.split('"span_id": "')[1].split('"')[0]
            if 'concepts' in schema['properties']:
                return {'concepts':[{'label':s,'evidence_span_ids':[sid],'confidence':.8} for s in ['ATP','산소']]}
            return {'relations':[{'source':'C1','target':'C0','relation':'related_to','evidence_span_ids':[sid],
                              'statement':'합성 이미지 연결 검증','conditions':[],'confidence':.8}]}
        with patch.dict(os.environ,{'NVIDIA_API_KEY':'fixture','NVIDIA_LOG_DIR':str(self.root/'logs')},clear=True):
            provider=NvidiaProvider(env_file=self.root/'missing.env')
            with patch.object(NvidiaProvider,'complete',complete):
                from backspace_mvp.semantic_control import SemanticControl
                from test_teacher_update import TeacherJev
                ex=StagedExtractor(provider,empty_dataset(),source,self.root/'checkpoints',visual_inputs=inputs)
                ex.span_control=SemanticControl(self.root/'span_decisions',provider=TeacherJev())
                data=ex.extract()
        self.assertEqual([stage.split(':p1')[0] for stage,_ in seen[:3]],['span:A','span:B','span:B_visual_review'])
        self.assertTrue(all(has_images for _,has_images in seen[:3]))
        self.assertEqual(data['sources'][0]['visual_context']['p1'],report)
        self.assertEqual(data['material_observations'][0]['evidence'][0]['quote'],source['excerpts'][0]['text'])
        self.assertTrue(data['material_observations'][0]['evidence'][0]['span_id'])
        self.assertEqual(data['material_relations'][0]['visual_context_hash'],report['content_hash'])
        from backspace_mvp.materials import export_material_graph
        graph=export_material_graph(data,self.root/'graph.json')
        self.assertEqual(graph['relations'][0]['assertions'][0]['visual_context_hash'],report['content_hash'])
        data['material_relations'][0]['visual_context_hash']='0'*64
        with self.assertRaisesRegex(ValueError,'matching page'):validate(data)

    def test_pdf_overview_includes_page_even_without_embedded_images(self):
        from reportlab.pdfgen.canvas import Canvas
        path=self.root/'diagram.pdf';pdf=Canvas(str(path),pagesize=(400,300));pdf.drawString(50,250,'ATP');pdf.line(50,240,150,240);pdf.save()
        doc,manifest=extract_document(path,self.root/'pdf_perception',reader=Reader())
        report=analyze_page(path,manifest,'p1',self.provider())
        self.assertTrue(report['coverage']['full_page_image'])
        self.assertEqual(report['images'][0]['id'],'page')
        self.assertTrue(all((manifest.parent/i['file']).stat().st_size<=170000 for i in report['images']))

    def test_path_traversal_and_changed_original_rejected(self):
        with self.assertRaises(ValueError):analyze_page(self.path,self.manifest,'../.env',self.provider())
        self.path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'원본 파일'):analyze_page(self.path,self.manifest,'p1',self.provider())


if __name__=='__main__': unittest.main()
