"""Disposable browser QA with latest backend, fixture files and external API blocked."""
import shutil
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from backspace_mvp.web import ROOT, WebStore, make_server
from backspace_mvp.pipeline import save

folder = Path(tempfile.mkdtemp(prefix='runtime-qa-', dir=ROOT/'output/playwright'))
shutil.copytree(ROOT/'state/web/demo', folder/'demo')
patch('urllib.request.urlopen', side_effect=AssertionError('External API disabled in browser verification')).start()
store = WebStore(storage=folder)
row = store.upload('ATP 생성과 세포 호흡. 원문 보존 확인.'.encode('utf-8'), '검증용 학습자료.txt', 'teacher', 'material')
store.upload('새 시험범위 자료. 기관계의 통합적 작용.'.encode('utf-8'), '검증용 시험범위.txt', 'scope', 'material')
original = store._read_file
def delayed_read(row, progress):
    time.sleep(8)
    return original(row, progress)
store._read_file = delayed_read
server = make_server(0, store)
save(ROOT/'output/playwright/runtime_qa_server.json', {'url':'http://127.0.0.1:'+str(server.server_port),
    'storage':str(folder), 'fixture_file_id':row['id'], 'external_api_blocked':True})
timer = threading.Timer(900, server.shutdown); timer.daemon=True; timer.start()
print('Isolated QA http://127.0.0.1:'+str(server.server_port), flush=True)
try: server.serve_forever()
finally: server.server_close()
