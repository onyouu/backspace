"""TypeSafe typed decisions. Credentials/provider error bodies are never logged."""
import json
import math
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv


class JevProvider:
    endpoint = 'https://api.typesafe.ai/v1/systemone'

    def __init__(self, env_file=Path('.env'), usage_path=None):
        load_dotenv(env_file, override=False)
        self.key = os.environ.get('TYPESAFE_API_KEY', '').strip()
        if not self.key:
            raise ValueError('.env에 TYPESAFE_API_KEY를 설정하세요.')
        self.model = os.environ.get('JEV_MODEL', 'jev-latest')
        self.timeout = int(os.environ.get('JEV_TIMEOUT_SECONDS', '45'))
        if self.timeout <= 0:
            raise ValueError('JEV_TIMEOUT_SECONDS는 양수여야 합니다.')
        self.usage_path = Path(usage_path) if usage_path else None
        self.run_id = 'jev_' + uuid.uuid4().hex
        self.attempts = []

    @staticmethod
    def validate_response(raw, questions):
        if not isinstance(raw, dict) or not isinstance(raw.get('model'), str):
            raise ValueError('Jev 응답 model이 없습니다.')
        answers = raw.get('answers')
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise ValueError('Jev 응답 질문 ID가 요청과 다릅니다.')
        for qid, question in questions.items():
            answer = answers[qid]
            kind = question['type']
            if not isinstance(answer, dict) or answer.get('type') != kind:
                raise ValueError('Jev 응답 type이 질문과 다릅니다.')
            if kind == 'noul':
                value = answer.get('noul')
                if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('Jev Noul 값이 유효하지 않습니다.')
                # Noul is a probability; the API supplies no separate confidence.
                continue
            levels = question['criteria']
            expected = {str(i): level for i, level in enumerate(levels)} if kind == 'score' else levels
            if kind == 'score' and answer.get('legend') != expected:
                raise ValueError('Jev Score type/legend가 기준표와 다릅니다.')
            if kind == 'choice' and answer.get('choice') not in expected:
                raise ValueError('Jev Choice가 요청 후보와 다릅니다.')
            probabilities = answer.get('probabilities')
            if not isinstance(probabilities, dict) or set(probabilities) != set(expected):
                raise ValueError('Jev Score 분포의 level이 다릅니다.')
            values = [answer.get('confidence'), *probabilities.values()]
            if kind == 'score': values.append(answer.get('score'))
            for value in values:
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                    raise ValueError('Jev Score 값이 유효한 수가 아닙니다.')
            if not ((kind != 'score' or 0 <= answer['score'] <= len(levels) - 1) and 0 <= answer['confidence'] <= 1
                    and all(0 <= p <= 1 for p in probabilities.values())
                    and abs(sum(probabilities.values()) - 1) <= 0.02):
                raise ValueError('Jev Score 값/분포 범위가 잘못됐습니다.')
        return {k: raw[k] for k in ('model', 'answers')} | {'usage': raw.get('usage')}

    def score(self, state, questions, *, stage):
        if not questions or any(q.get('type') != 'score' or not 2 <= len(q.get('criteria', [])) <= 10
                                for q in questions.values()):
            raise ValueError('Jev 요청은 2~10개 서술형 level의 독립 Score 질문이어야 합니다.')
        return self.decide(state, questions, stage=stage)

    def decide(self, state, questions, *, stage):
        if not questions:
            raise ValueError('Jev 질문이 없습니다.')
        for q in questions.values():
            kind, criteria = q.get('type'), q.get('criteria')
            if not q.get('instructions') or kind not in ('noul','choice','score'):
                raise ValueError('Jev typed question 계약이 다릅니다.')
            if kind == 'score' and (not isinstance(criteria,list) or not 2 <= len(criteria) <= 10):
                raise ValueError('Jev Score 기준은 2~10개입니다.')
            if kind == 'choice' and (not isinstance(criteria,dict) or not 2 <= len(criteria) <= 255):
                raise ValueError('Jev Choice 후보는 2~255개입니다.')
        payload = {'model': self.model, 'state': json.dumps(state, ensure_ascii=False), 'questions': questions}
        event = {'stage': stage, 'model': self.model, 'status': 'started',
                 'question_count': len(questions), 'timeout_seconds': self.timeout}
        self.attempts.append(event)
        started = time.monotonic()
        try:
            request = urllib.request.Request(self.endpoint, json.dumps(payload, ensure_ascii=False).encode(),
                headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.load(response)
            result = self.validate_response(raw, questions)
            event.update(status='success', actual_model=result['model'], usage=result['usage'])
            return result
        except urllib.error.HTTPError as exc:
            event.update(status='http_error', http_status=exc.code)
            raise ValueError(f'Jev HTTP {exc.code}: 키·접근 권한·사용량을 확인하세요.') from None
        except (TimeoutError, urllib.error.URLError):
            event['status'] = 'transport_error'
            raise ValueError('Jev 연결 실패 또는 시간 초과. 완료된 점수는 체크포인트에서 재사용합니다.') from None
        except (ValueError, TypeError, KeyError):
            event['status'] = 'invalid_response'
            raise ValueError('Jev 응답 형식 또는 typed decision 계약이 다릅니다. 기존 상태는 유지합니다.') from None
        finally:
            event['elapsed_seconds'] = round(time.monotonic() - started, 3)
            if self.usage_path:
                from .pipeline import save
                from .model import read_json
                value = read_json(self.usage_path) if self.usage_path.exists() else {'schema_version': '1.0', 'runs': {}}
                value['runs'][self.run_id] = {'provider': 'typesafe', 'role': 'typed_decisions',
                                            'attempts': self.attempts, 'cost': None}
                value['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                save(self.usage_path, value)
