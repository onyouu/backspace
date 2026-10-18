import io
import json
import unittest
from backspace_mvp.nvidia import read_completion_stream, InvalidResponseError


def stream(*items):
    return io.BytesIO(''.join('data: '+(item if isinstance(item,str) else json.dumps(item))+'\n\n' for item in items).encode())


class VisionStreamTests(unittest.TestCase):
    def test_collects_only_answer_and_usage(self):
        result=read_completion_stream(stream(
            {'choices':[{'index':0,'delta':{'reasoning_content':'private trace'}}]},
            {'choices':[{'index':0,'delta':{'content':'{"ok":'}}]},
            {'choices':[{'index':0,'delta':{'content':'true}'},'finish_reason':'stop'}]},
            {'choices':[],'usage':{'completion_tokens':9}}, '[DONE]'),1)
        self.assertEqual(result['choices'][0]['message']['content'],'{"ok":true}')
        self.assertEqual(result['usage'],{'completion_tokens':9})

    def test_missing_terminal_or_finish_is_rejected(self):
        for response in [stream({'choices':[{'delta':{'content':'{}'},'finish_reason':'stop'}]}),
                         stream({'choices':[{'delta':{'content':'{}'}}]},'[DONE]')]:
            with self.assertRaisesRegex(InvalidResponseError,'incomplete_response'):
                read_completion_stream(response,1)

    def test_length_finish_remains_length_for_caller(self):
        result=read_completion_stream(stream({'choices':[{'delta':{'content':'{'},'finish_reason':'length'}]},'[DONE]'),1)
        self.assertEqual(result['choices'][0]['finish_reason'],'length')


if __name__=='__main__': unittest.main()
