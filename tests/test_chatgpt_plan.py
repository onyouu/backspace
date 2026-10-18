import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from backspace_mvp import chatgpt_auth as auth
from backspace_mvp.chatgpt_plan import ChatGPTPlanProvider, read_stream
from backspace_mvp.nvidia import ProviderStageFailure


class ChatGPTPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.storage=patch.object(auth,'auth_dir',return_value=self.root/'auth');self.storage.start()
    def tearDown(self):
        self.storage.stop();self.temp.cleanup()
    def seed(self):
        with auth.locked(self.root) as folder:
            data=auth._read(folder)
            data.update(enabled=True,active='account')
            data['accounts']['account']={'client_id':'issued','subject':'s','access_token':'secret-access',
                'refresh_token':'secret-refresh','id_token':'secret-id','scopes':['chatgpt.tokens.use.direct'],
                'expires_at':time.time()+3600,'model':'visible-model','models':[{'slug':'visible-model','display_name':'Model'}]}
            auth._write(folder,data)
    def test_encrypted_storage_and_safe_status(self):
        self.seed();raw=(self.root/'auth/accounts.bin').read_bytes()
        import os
        if os.name=='nt':self.assertNotIn(b'secret-access',raw)
        safe=json.dumps(auth.status(self.root));self.assertNotIn('secret-',safe)
        self.assertEqual(auth.access(self.root)[0],'secret-access')
    def test_pkce_and_single_use_callback(self):
        with patch.object(auth.webbrowser,'open',return_value=True) as browser:
            auth.begin(self.root,8786)
            query=parse_qs(urlsplit(browser.call_args.args[0]).query)
        self.assertEqual(query['client_id'],['dynamic_agent_client'])
        self.assertEqual(query['code_challenge_method'],['S256'])
        self.assertEqual(query['redirect_uri'],['http://127.0.0.1:8786/auth/callback'])
        cb={'state':query['state'],'code':['code'],'client_id':['issued']}
        tokens={'access_token':'secret','refresh_token':'refresh','id_token':'identity','token_type':'Bearer','scope':auth.SCOPES,'expires_in':3600}
        with patch.object(auth,'_json_request',return_value=tokens) as request, patch.object(auth,'validate_identity',return_value={'sub':'subject','email':'user'}),patch.object(auth,'refresh_models'):
            auth.callback(self.root,cb)
            form=request.call_args.args[1]
            self.assertEqual(form['client_id'],'issued');self.assertIn('code_verifier',form)
            with self.assertRaises(ValueError):auth.callback(self.root,cb)
        self.assertTrue(auth.status(self.root)['plan_allowed'])
    def test_bad_state_and_denied_do_not_exchange(self):
        with patch.object(auth,'_json_request') as request:
            with self.assertRaises(ValueError):auth.callback(self.root,{'state':['wrong'],'code':['x']})
            request.assert_not_called()
        with patch.object(auth.webbrowser,'open',return_value=True) as browser:auth.begin(self.root,8786)
        q=parse_qs(urlsplit(browser.call_args.args[0]).query)
        with patch.object(auth,'_json_request') as request:
            with self.assertRaises(ValueError):auth.callback(self.root,{'state':q['state'],'error':['access_denied']})
            request.assert_not_called()
    def test_returning_client_mismatch(self):
        self.seed()
        with patch.object(auth.webbrowser,'open',return_value=True) as browser:auth.begin(self.root,8786,'account')
        q=parse_qs(urlsplit(browser.call_args.args[0]).query)
        self.assertEqual(q['client_id'],['issued']);self.assertNotIn('agent_name_hint',q)
        with self.assertRaises(ValueError):auth.callback(self.root,{'state':q['state'],'code':['x'],'client_id':['other']})
    def test_signature_nonce_and_identity_validation(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        claims={'sub':'s','iat':int(time.time()),'exp':int(time.time())+300,'nonce':'nonce','aud':'client','iss':auth.ISSUER}
        token=jwt.encode(claims,key,algorithm='RS256')
        with patch('jwt.PyJWKClient') as jwks:
            jwks.return_value.get_signing_key_from_jwt.return_value.key=key.public_key()
            self.assertEqual(auth.validate_identity(token,'client','nonce')['sub'],'s')
            for client,nonce in [('wrong','nonce'),('client','wrong')]:
                with self.assertRaises(ValueError):auth.validate_identity(token,client,nonce)
            claims['exp']=int(time.time())-60
            with self.assertRaises(ValueError):auth.validate_identity(jwt.encode(claims,key,algorithm='RS256'),'client','nonce')
    def test_refresh_rotation(self):
        self.seed()
        with auth.locked(self.root) as folder:
            d=auth._read(folder);d['accounts']['account']['expires_at']=0;auth._write(folder,d)
        with patch.object(auth,'_json_request',return_value={'access_token':'new','refresh_token':'rotated','expires_in':3600}) as request:
            self.assertEqual(auth.access(self.root)[0],'new');self.assertEqual(auth.access(self.root)[0],'new')
            self.assertEqual(request.call_count,1)
        with auth.locked(self.root) as folder:self.assertEqual(auth._read(folder)['accounts']['account']['refresh_token'],'rotated')
    def test_logout_clears_credentials_but_retains_registration(self):
        self.seed()
        with patch.object(auth,'_json_request',side_effect=[{'revocation_endpoint':auth.ISSUER+'/revoke'},ValueError('temporary'),{}]) as request,patch.object(auth.time,'sleep'):
            result=auth.sign_out(self.root)
            self.assertEqual(request.call_count,3)
        self.assertFalse(result['connected']);self.assertTrue(result['enabled'])
        with auth.locked(self.root) as folder:
            record=auth._read(folder)['accounts']['account']
        self.assertEqual(record['client_id'],'issued')
        for field in ('access_token','refresh_token','id_token'):self.assertNotIn(field,record)
    def test_stream_requires_terminal_success(self):
        partial=b'data: {"type":"response.output_text.delta","delta":"hello"}\n\n'
        with self.assertRaises(ValueError):read_stream(io.BytesIO(partial),10)
        failed=partial+b'data: {"type":"response.failed","response":{"error":{"code":"subscription_sharing_usage_limit_exceeded"}}}\n'
        with self.assertRaisesRegex(ValueError,'한도'):read_stream(io.BytesIO(failed),10)
        done=partial+b'data: {"type":"response.completed","response":{"usage":{"input_tokens":3}}}\n'
        self.assertEqual(read_stream(io.BytesIO(done),10),('hello',{'input_tokens':3}))
    def test_provider_payload_cache_and_no_paid_fallback(self):
        self.seed();provider=ChatGPTPlanProvider(self.root/'.env')
        schema={'type':'object','properties':{'value':{'type':'integer'}},'required':['value']}
        body=('data: '+json.dumps({'type':'response.output_text.delta','delta':'{"value":1}'})+'\n\n'+'data: '+json.dumps({'type':'response.completed','response':{'usage':{'input_tokens':3,'output_tokens':4,'total_tokens':7}}})+'\n').encode()
        with patch('urllib.request.urlopen',return_value=io.BytesIO(body)) as request:
            self.assertEqual(provider.complete('p',schema),{'value':1})
            payload=json.loads(request.call_args.args[0].data)
            self.assertTrue(payload['stream']);self.assertFalse(payload['store']);self.assertIsInstance(payload['input'],list)
            for field in ('max_output_tokens','temperature','conversation','previous_response_id'):self.assertNotIn(field,payload)
            self.assertEqual(provider.complete('p',schema),{'value':1});self.assertEqual(request.call_count,1)
        self.assertEqual(provider.attempts[-1]['status'],'cache_hit')
    def test_failed_stream_not_cached(self):
        self.seed();provider=ChatGPTPlanProvider(self.root/'.env')
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'data: {"type":"response.output_text.delta","delta":"partial"}\n')):
            with self.assertRaises(ProviderStageFailure):provider.complete_text('p')
        self.assertFalse(list(provider.cache_dir.glob('*.json')))


if __name__=='__main__':unittest.main()
