"""Local ONNX execution of the official multilingual SentenceTransformer model."""
from functools import lru_cache
import json
import threading

MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
REVISION='e8f8c211226b894fcb81acc59f3b34ba3efd5f42'


class MultilingualONNXEmbedding:
    def __init__(self,model_name=MODEL):
        if model_name!=MODEL:
            raise ValueError('현재 ONNX 메모리 임베딩은 고정된 다국어 MiniLM 모델만 지원합니다.')
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        import onnxruntime as ort
        def asset(name):
            return hf_hub_download(model_name,name,revision=REVISION)
        self.model_name=model_name
        self.tokenizer=Tokenizer.from_file(asset('tokenizer.json'))
        with open(asset('sentence_bert_config.json'),encoding='utf-8') as stream:
            limit=json.load(stream)['max_seq_length']
        with open(asset('1_Pooling/config.json'),encoding='utf-8') as stream:
            pooling=json.load(stream)
        if not pooling['pooling_mode_mean_tokens']:
            raise ValueError('고정 모델의 mean pooling 설정이 다릅니다.')
        self.tokenizer.enable_truncation(max_length=limit)
        self.tokenizer.enable_padding(pad_id=0,pad_token='<pad>')
        options=ort.SessionOptions();options.intra_op_num_threads=4
        self.session=ort.InferenceSession(asset('onnx/model_quint8_avx2.onnx'),
            sess_options=options,providers=['CPUExecutionProvider'])
        self.lock=threading.Lock()

    def __call__(self,input):
        import numpy as np
        rows=[]
        # Batch and tokenizer state are bounded; the session never calls an inference API.
        with self.lock:
            for start in range(0,len(input),16):
                encoded=self.tokenizer.encode_batch(input[start:start+16])
                tensors={'input_ids':np.asarray([e.ids for e in encoded],dtype=np.int64),
                    'attention_mask':np.asarray([e.attention_mask for e in encoded],dtype=np.int64),
                    'token_type_ids':np.asarray([e.type_ids for e in encoded],dtype=np.int64)}
                output=self.session.run(None,{i.name:tensors[i.name] for i in self.session.get_inputs()})[0]
                mask=tensors['attention_mask'][...,None]
                pooled=(output*mask).sum(axis=1)/np.maximum(mask.sum(axis=1),1)
                pooled=pooled/np.maximum(np.linalg.norm(pooled,axis=1,keepdims=True),1e-12)
                rows.extend(pooled.astype(np.float32))
        return rows

    def embed_query(self,input):return self(input)
    @staticmethod
    def name():return 'backspace-multilingual-minilm-onnx'
    def get_config(self):return {'model_name':self.model_name,'revision':REVISION}
    @staticmethod
    def build_from_config(config):
        if config.get('revision',REVISION)!=REVISION:raise ValueError('임베딩 버전이 다릅니다.')
        return multilingual_embedding(config.get('model_name',MODEL))
    def is_legacy(self):return False
    def default_space(self):return 'cosine'
    def supported_spaces(self):return ['cosine']


@lru_cache(maxsize=2)
def multilingual_embedding(model_name=MODEL):
    return MultilingualONNXEmbedding(model_name)
