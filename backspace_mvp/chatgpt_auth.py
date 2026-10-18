"""Official public-client Sign in with ChatGPT; no Codex credential reuse.

Credentials stay outside the workspace, protected by Windows DPAPI (0600 on
Unix). Callback transactions are short lived and single use. All callers share
an OS file lock while reading/rotating credentials.
"""
import base64
import ctypes
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from contextlib import contextmanager
from pathlib import Path

ISSUER = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
TOKEN_URL = ISSUER + '/api/accounts/oauth/token'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
_mutex = threading.RLock()
_pending = {}


def auth_dir(root):
    base = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.local/share'))
    return base/'Backspace'/'chatgpt'/hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:20]


def _protect(data, decrypt=False):
    if os.name != 'nt':
        return data
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    out = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(out)):
        raise ValueError('이 컴퓨터의 ChatGPT 연결 정보를 읽거나 보호하지 못했습니다.')
    try:
        return ctypes.string_at(out.data, out.size)
    finally:
        ctypes.windll.kernel32.LocalFree(out.data)


@contextmanager
def locked(root):
    with _mutex:
        folder = auth_dir(root)
        folder.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt': os.chmod(folder, 0o700)
        with (folder/'session.lock').open('a+b') as lock:
            if lock.tell() == 0: lock.write(b'0'); lock.flush()
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX)
            try: yield folder
            finally:
                lock.seek(0)
                if os.name == 'nt': msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(lock, fcntl.LOCK_UN)


def _read(folder):
    path = folder/'accounts.bin'
    if not path.exists():
        return {'host_id': 'urn:uuid:'+str(uuid.uuid4()), 'accounts': {}, 'active': None, 'enabled': False}
    return json.loads(_protect(path.read_bytes(), True))


def _write(folder, data):
    path = folder/('accounts.'+uuid.uuid4().hex+'.tmp')
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(_protect(json.dumps(data).encode())); f.flush(); os.fsync(f.fileno())
    os.replace(path, folder/'accounts.bin')


def _json_request(url, form=None, token=None):
    headers = {'Accept': 'application/json'}
    raw = None
    if form is not None:
        raw = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if token: headers['Authorization'] = 'Bearer '+token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=raw, headers=headers), timeout=25) as r:
            body = r.read(2_000_001)
            if len(body)>2_000_000: raise ValueError('ChatGPT 응답 크기가 너무 큽니다.')
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        # Never include token response bodies, callback parameters, or auth URLs.
        raise ValueError('ChatGPT 연결 요청 실패 (HTTP '+str(exc.code)+'). 다시 로그인하거나 사용 한도를 확인하세요.') from None
    except (OSError, json.JSONDecodeError):
        raise ValueError('ChatGPT 연결 서버에 접속하지 못했습니다. 잠시 후 다시 시도하세요.') from None


def status(root):
    with locked(root) as folder:
        data = _read(folder)
        active = data['accounts'].get(data['active'], {})
        accounts = [{'id': key, 'label': a.get('email','ChatGPT')+' · '+key[-6:],
                     'connected': bool(a.get('refresh_token'))} for key,a in data['accounts'].items()]
        return {'enabled': data['enabled'], 'connected': bool(active.get('access_token')),
                'plan_allowed': 'chatgpt.tokens.use.direct' in active.get('scopes', []),
                'active': data['active'], 'accounts': accounts, 'model': active.get('model'),
                'models': active.get('models', []), 'message': data.get('message',''),
                'usage_url': 'https://chatgpt.com/settings/usage'}


def begin(root, port, account=None):
    with locked(root) as folder:
        data = _read(folder)
        saved = data['accounts'].get(account) if account else None
        if account and not saved: raise ValueError('저장된 계정을 찾을 수 없습니다.')
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        redirect = f'http://127.0.0.1:{port}/auth/callback'
        client = saved['client_id'] if saved else 'dynamic_agent_client'
        _pending[state] = {'root': str(Path(root).resolve()), 'nonce':nonce, 'verifier':verifier,
                           'redirect':redirect, 'client':client, 'subject':saved.get('subject') if saved else None,
                           'created':time.time()}
        for key in list(_pending):
            if time.time()-_pending[key]['created']>600: _pending.pop(key)
        params = {'client_id':client, 'ext_agent_host_id':data['host_id'], 'response_type':'code',
                  'redirect_uri':redirect, 'scope':SCOPES, 'resource':RESOURCE, 'state':state,
                  'nonce':nonce, 'code_challenge_method':'S256',
                  'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
        if saved:
            if saved.get('id_token'): params['id_token_hint']=saved['id_token']
            if saved.get('email'): params['login_hint']=saved['email']
        else: params['agent_name_hint']='Backspace'
        data['message']='열린 브라우저에서 로그인과 구독 사용 허용을 완료하세요.'
        _write(folder,data)
    # Keep authorization URLs (which may carry an ID-token hint) off app JSON APIs.
    if not webbrowser.open(ISSUER+'/api/accounts/authorize?'+urllib.parse.urlencode(params)):
        raise ValueError('기본 브라우저를 열지 못했습니다. 기본 브라우저 설정을 확인하세요.')
    return {'started':True}


def validate_identity(token, client, nonce):
    import jwt
    try:
        jwks = jwt.PyJWKClient(ISSUER+'/.well-known/jwks.json', timeout=20)
        key = jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=['RS256','ES256'], issuer=ISSUER,
                            audience=client, leeway=5, options={'require':['sub','exp','iat','nonce']})
        if not secrets.compare_digest(str(claims['nonce']),nonce): raise ValueError()
        return claims
    except Exception:
        raise ValueError('ChatGPT 로그인 응답의 서명 또는 계정을 검증하지 못했습니다. 다시 로그인하세요.') from None


def callback(root, query):
    state = query.get('state',[''])[0]
    with _mutex:
        pending = _pending.pop(state,None)
    if not pending or pending['root']!=str(Path(root).resolve()) or time.time()-pending['created']>600:
        raise ValueError('로그인 요청이 만료됐거나 일치하지 않습니다. 앱에서 다시 로그인하세요.')
    if query.get('error'): raise ValueError('ChatGPT 연결이 승인되지 않았습니다. 앱에서 다시 시도할 수 있습니다.')
    client = query.get('client_id',[pending['client']])[0]
    if client=='dynamic_agent_client' or (pending['client']!='dynamic_agent_client' and client!=pending['client']):
        raise ValueError('ChatGPT 앱 등록 정보가 일치하지 않습니다.')
    code=query.get('code',[''])[0]
    if not code: raise ValueError('로그인 코드가 없습니다. 다시 로그인하세요.')
    tokens=_json_request(TOKEN_URL, {'grant_type':'authorization_code','client_id':client,'code':code,
        'code_verifier':pending['verifier'],'redirect_uri':pending['redirect'],'resource':RESOURCE})
    claims=validate_identity(tokens.get('id_token',''),client,pending['nonce'])
    if pending['subject'] and claims['sub']!=pending['subject']:
        raise ValueError('선택한 계정과 로그인 계정이 다릅니다.')
    if tokens.get('token_type','').lower()!='bearer' or not tokens.get('access_token'):
        raise ValueError('ChatGPT 연결 자격 증명이 없습니다.')
    scopes=tokens.get('scope','').split()
    with locked(root) as folder:
        data=_read(folder)
        key=hashlib.sha256((client+'\0'+claims['sub']).encode()).hexdigest()[:24]
        record={'client_id':client,'subject':claims['sub'],'email':claims.get('email','ChatGPT'),
                'scopes':scopes,'expires_at':time.time()+int(tokens.get('expires_in',3600)),
                **{k:tokens.get(k) for k in ('access_token','refresh_token','id_token','earliest_refresh_at')}}
        data['accounts'][key]=record;data['active']=key;data['enabled']=True
        data['message']='로그인 완료. 사용할 모델을 선택하세요.' if 'chatgpt.tokens.use.direct' in scopes else '로그인은 완료됐지만 구독 사용 권한은 허용되지 않았습니다.'
        _write(folder,data)
    if 'chatgpt.tokens.use.direct' in scopes: refresh_models(root)


def access(root):
    with locked(root) as folder:
        data=_read(folder);record=data['accounts'].get(data['active'],{})
        if not record.get('access_token') or 'chatgpt.tokens.use.direct' not in record.get('scopes',[]):
            raise ValueError('ChatGPT에 로그인하고 구독 사용을 허용하세요.')
        if record['expires_at']<time.time()+60:
            if not record.get('refresh_token'): raise ValueError('ChatGPT에 다시 로그인하세요.')
            tokens=_json_request(TOKEN_URL,{'grant_type':'refresh_token','client_id':record['client_id'],
                'refresh_token':record['refresh_token'],'resource':RESOURCE})
            if not tokens.get('access_token') or not tokens.get('refresh_token'):
                raise ValueError('ChatGPT 세션 갱신이 완료되지 않았습니다. 다시 로그인하세요.')
            record.update({k:tokens[k] for k in ('access_token','refresh_token')})
            if tokens.get('id_token'): record['id_token']=tokens['id_token']
            record['scopes']=tokens.get('scope',' '.join(record['scopes'])).split()
            record['expires_at']=time.time()+int(tokens.get('expires_in',3600))
            _write(folder,data)
            if 'chatgpt.tokens.use.direct' not in record['scopes']: raise ValueError('구독 사용 권한을 다시 허용하세요.')
        return record['access_token'], data['active'], record.get('model')


def refresh_models(root):
    token,account,_=access(root)
    raw=_json_request(RESOURCE+'/models',token=token)
    models=[{'slug':m['slug'],'display_name':m.get('display_name',m['slug'])} for m in raw.get('models',[])
            if m.get('visibility')=='list' and isinstance(m.get('slug'),str)]
    with locked(root) as folder:
        data=_read(folder);record=data['accounts'][account];record['models']=models
        if record.get('model') not in [m['slug'] for m in models]: record['model']=None
        _write(folder,data)
    return status(root)


def select(root, account=None, model=None):
    with locked(root) as folder:
        data=_read(folder)
        if account:
            if account not in data['accounts']: raise ValueError('계정을 찾을 수 없습니다.')
            data['active']=account;data['enabled']=True
        record=data['accounts'].get(data['active'],{})
        if model is not None:
            if model not in [m['slug'] for m in record.get('models',[])]: raise ValueError('이 계정의 모델 목록에서 선택하세요.')
            record['model']=model
            data['message']='연결 준비 완료. 선택한 모델로 분석합니다.'
        _write(folder,data)
    if account: return refresh_models(root)
    return status(root)


def sign_out(root):
    confirmed=False
    with locked(root) as folder:
        data=_read(folder);record=data['accounts'].get(data['active'],{})
        try:
            discovery=_json_request(ISSUER+'/.well-known/openid-configuration')
            endpoint=discovery.get('revocation_endpoint','')
            if not endpoint.startswith(ISSUER+'/'): raise ValueError('invalid_endpoint')
            if record.get('refresh_token'):
                form={'token':record['refresh_token'],'token_type_hint':'refresh_token','client_id':record['client_id']}
                try:_json_request(endpoint,form)
                except ValueError:
                    time.sleep(1)
                    _json_request(endpoint,form)
            confirmed=True
        except ValueError: pass
        for key in ('access_token','refresh_token','id_token'): record.pop(key,None)
        record['models']=[];record['model']=None
        data['message']='로그아웃했습니다.' if confirmed else '로컬 로그아웃 완료. 원격 연결 해제는 확인되지 않았습니다. ChatGPT 설정에서 연결을 해제할 수 있습니다.'
        _write(folder,data)
    return status(root)
