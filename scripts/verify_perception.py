"""Bounded real-document OCR review. No NVIDIA/Jev calls, no source edits."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
from backspace_mvp.perception import extract_document
from backspace_mvp.pipeline import save

root=Path(__file__).resolve().parents[1]
files=json.loads((root/'state/web/workspace/files.json').read_text(encoding='utf-8'))
out=root/'output/perception_review'
rows=[]
for n,row in enumerate(files[:3],1):
    path=root/'state/web/workspace/uploads'/(row['id']+row['suffix'])
    print('Document',n,flush=True)
    doc,manifest=extract_document(path,out, page_range=[1,2,3,4],
        progress=lambda loc,count:print('saved',loc,flush=True))
    for page in doc['pages']:
        for asset in page['assets']:
            im=Image.open(manifest.parent/asset['file']).convert('RGB')
            draw=ImageDraw.Draw(im)
            box=asset['bbox'];w=box[2]-box[0];h=box[3]-box[1]
            for block in page['blocks']:
                if block['asset_id']==asset['id']:
                    b=block['bbox']; rect=[(b[0]-box[0])*im.width/w,(b[1]-box[1])*im.height/h,(b[2]-box[0])*im.width/w,(b[3]-box[1])*im.height/h]
                    draw.rectangle(rect,outline='orange' if block['status']=='needs_review' else '#008040',width=2)
            im.thumbnail((1050,850))
            im.save(out/f'doc{n}-{page["locator"]}-{asset["id"]}.png')
    rows.append({'file_id':row['id'],'name':row['name'],'selected_pages':[1,2,3,4],
        'manifest':str(manifest.relative_to(root)), 'coverage':doc['coverage'],
        'pages':[{'locator':p['locator'],'status':p['status'],'chars':len(p['text']),
            'native_blocks':sum(b['method']=='native' for b in p['blocks']),
            'ocr_blocks':sum(b['method']=='paddle' for b in p['blocks']),
            'pending_blocks':p['pending_blocks'],'errors':p['errors']} for p in doc['pages']]})
    save(out/'verification.json',{'external_ai_calls':0,'documents':rows,'scope':'first four pages of three uploaded PDFs'})
print('Saved verification.json',flush=True)
