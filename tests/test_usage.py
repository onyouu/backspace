import json
import tempfile
import unittest
from pathlib import Path
from backspace_mvp.usage import usage_summary


class UsageTests(unittest.TestCase):
    def test_mixed_provider_counters_and_cache_do_not_double_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'usage.json'
            path.write_text(json.dumps({'runs':{
                'chatgpt':{'attempts':[{'status':'success','network_attempts':1,'usage':{'prompt_tokens':100,'completion_tokens':20,'thought_tokens':5,'total_tokens':120}}]},
                'jev':{'attempts':[{'status':'success','usage':{'input_tokens':30,'output_tokens':4}}]},
                'cached':{'attempts':[{'status':'cache_hit','network_attempts':0,'usage':{'prompt_tokens':0,'completion_tokens':0,'total_tokens':0},'avoided_usage':{'input_tokens':30,'output_tokens':4}}]},
                'failed':{'attempts':[{'status':'provider_error','network_attempts':1}]}
            }}),encoding='utf-8')
            result=usage_summary(path)
            self.assertEqual(result['requests'],3)
            self.assertEqual(result['cache_hits'],1)
            self.assertEqual(result['input_tokens'],130)
            self.assertEqual(result['output_tokens'],24)
            self.assertEqual(result['total_tokens'],154)
            self.assertEqual(result['thought_tokens'],5)
            self.assertEqual(result['avoided_tokens'],34)

    def test_absent_log_has_no_observed_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            result=usage_summary(Path(folder)/'missing.json')
            self.assertEqual(result['requests'],0)
            self.assertEqual(result['total_tokens'],0)
            self.assertEqual(result['cost_status'],'not_measured')
