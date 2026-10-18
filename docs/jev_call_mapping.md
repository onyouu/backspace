# NVIDIA 호출 점검 — Jev를 먼저 붙일 위치

코드를 수정하기 전에 확인한 현재 호출 지도다. 시간 제한을 늘리는 변경을 우선 해법으로 사용하지 않는다.

| 현재 호출 | 호출이 필요한 이유 | 이번 처리 |
|---|---|---|
| `understanding.py`의 자연어 이해 노트 | 글자의 의미를 새로 정리 | LLM 유지. 실패하면 원문 단위를 줄이고 완료한 노트는 보존 |
| `amem_adapter.py`의 metadata | 노트의 keywords/context/tags 생성 | 노트와 관련 기억을 Jev가 먼저 판단. 충분히 확실한 기존 내용이면 Python이 기존 분류·문맥을 재사용 |
| A-MEM `process_memory`의 evolution | 이웃 기억의 새로운 연결·문맥 해석 | Jev relation/gate로 제한. 명확한 기존 연결은 Python, 새 해석·충돌·불확실성은 기존 LLM evolution |
| `grounded.py`의 자료 개념/관계 생성 | 원문을 검증 가능한 작은 그래프로 표현 | Jev graph gate가 필요성을 판단. 생략을 별도 기록하며 원문과 이해 노트는 유지 |
| `grounded.py`의 관계 검토 | 추출 후보가 원문·조건·방향과 맞는지 확인 | 기존 검토 유지. 먼저 graph gate로 불필요한 생성·검토 쌍을 줄임 |
| `staged.py`의 시험 문항 분리·답안 기준 분석 | 새로운 문항 경계와 필요한 사고 생성 | LLM 유지. 시험을 학습자료 graph gate로 누락하지 않음 |
| `hypotheses.py`의 교사 가설 생성 | 반복 근거를 새로운 조건부 설명으로 묶음 | 기존 가설 생성 유지. 생성 후 Jev가 지지/반박/근거 강도/정당한 범위/재분석 필요성을 함께 검증 |
| `study_plan.py`의 과제 설명 생성 | 점수·시간을 공부 행동으로 번역 | 이번에는 planning gate의 입력·판단 계약만 준비. 기존 생성 흐름 유지 |
| `visual.py`의 선택 페이지 그림 해석 | 이미지의 배치·화살표·관계를 새로 해석 | VLM 유지. 텍스트 전용 Jev에 이미지를 해석시키지 않음 |

현재 `nvidia.py`는 답변 길이 제한에서 같은 요청의 토큰과 시간 제한을 늘리고 재호출한다. 이 동작을 semantic 단위 축소·선택 후 재호출로 바꾸며, 원래 timeout 설정값은 유지한다.

우선 구현: 노트 후 Jev Router → A-MEM의 느린 metadata/evolution gate → 자료 Graph Projection Gate → 생성 가설의 Jev typed validation. Teacher prefilter/update 및 planning은 확장 지점을 준비하되 네 단계와 동시에 전체 기능을 갈아엎지 않는다.

Jev 계약은 [공식 HTTP API](https://docs.typesafe.ai/api)를 기준으로 한다. Choice/Score의 confidence와 probability를 분리하며 Noul은 별도 confidence가 없는 yes 확률이다. 애매한 답은 false로 바꾸지 않고 기존 분석으로 넘긴다.
