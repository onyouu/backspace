# Backspace 개발 변천사

기준 시간대: Asia/Seoul (KST)

상태 표기:

- `IDEA` — 아이디어/방향 결정
- `DESIGN` — 아키텍처 설계
- `IMPLEMENTED` — 구현 완료가 대화에서 보고됨
- `VALIDATED` — 테스트/실자료 검증 결과가 보고됨
- `FAILURE` — 실제 실패 확인
- `PIVOT` — 실패를 바탕으로 구조 변경
- `NEXT` — 다음 구현 방향

---

# 2026년 4월 — 최초 Backspace 설계

## 2026-04 · IDEA

Backspace의 초기 형태가 만들어짐.

초기 목적:

> 학생의 성적과 학습 데이터를 장기간 기억하고 관리하는 개인 AI 학습 시스템

초기 구조:

```text
Teacher Agent
Student Agent
Coach Agent
```

입력 후보:

```text
시험지
PPT
Notion
성적
백지복습
이해도
학습 습관
개념 네트워크
```

초기 시스템 구상에는 다음도 포함됨.

```text
Telegram 중심 상호작용
웹 대시보드

03:00
에이전트 자율 분석

07:00
학생에게 아침 브리핑
```

초기 개발 로드맵:

```text
Phase 1
서버 + Bot + 시험지 OCR

Phase 2
Student Agent + Notion

Phase 3
Teacher Agent + RAG + 출제 패턴

Phase 4
Coach Agent + 자율 루프
```

이 시기의 Backspace는 지금보다 훨씬 큰 **개인 AI 교육 운영체제**에 가까웠음.

---

# 2026년 7월 — 초기 기획안 고정

## 2026-07-03 · DESIGN

초기 Backspace 기획 문서가 정리됨.

아직 실제 제품보다:

```text
Teacher
Student
Coach
RAG
OCR
자동 계획
성적 분석
자율 Agent
```

가 한 번에 들어간 대규모 구조에 가까웠음.

이후 실제 개발에서는 범위가 너무 크다는 문제가 지속적으로 등장함.

---

# 2026년 8월 30일 — Backspace 핵심 재정의

## 2026-08-30 16:05 · IDEA

초기 구상을 다시 설명.

핵심:

```text
나를 아는 AI 성적관리 시스템
```

Teacher / Student / Coach 구조를 유지하면서:

- 시험지
- 수업자료
- Notion
- 성적
- 이해도
- 습관
- 개념망

을 장기간 누적하는 방향.

Raspberry Pi 서버 운영도 고려함.

---

## 2026-08-30 16:05 · PIVOT

전체 플랫폼을 한 번에 구현하는 것은 너무 크다고 판단.

MVP를:

```text
개념
이해도
시험
오답
↓
약점 추적
```

중심으로 축소하는 안이 등장.

---

## 2026-08-30 16:06 · IDEA

Backspace의 본질이 다시 한 번 바뀜.

단순 성적관리보다:

> 인간이 스스로 놓치는 패턴과 작은 습관을 장기간 관찰하고, 과거의 나를 기억하는 AI

라는 개념이 중심이 됨.

구조 후보:

```text
Observer
Memory
Analyst
Coach
```

이때부터 **장기 기억과 패턴 발견**이 Backspace의 핵심 문제로 자리 잡음.

---

# 2026년 9월 4일 — 장기 프로젝트로 확정

## 2026-09-04 20:34 · DESIGN

초기 학습 분석 구조:

```text
학생 학습 데이터
      ↓
문제 패턴 분석 Agent

학생 상태 / 학습 패턴 분석 Agent
      ↓
종합 Agent
      ↓
학생 모델 지속 업데이트
```

핵심 목적은 문제를 대신 푸는 것이 아니라:

> 다음에 학생이 무엇을 해야 하는지를 결정하는 것

으로 정리됨.

---

## 2026-09-04 20:34 · PIVOT

Backspace의 철학적 방향이 크게 바뀜.

기존:

```text
AI
→ 답 제공
```

변경:

```text
학습 행동
→ AI 분석
→ 질문 / 대화
→ 자기 사고 성찰
→ 다음 행동
```

즉 AI를:

> 답변 도구가 아니라 학생의 사고를 다시 보게 만드는 사고 파트너

로 정의.

이 시점부터 Backspace를 단기 대회용 아이디어가 아니라 **약 3년 이상 계속 발전시킬 메인 프로젝트**로 보기 시작함.

---

# 2026년 9월 16일 — Teacher Agent가 핵심으로 부상

## 2026-09-16 15:03 · IDEA

Backspace 아이디어의 출발점을 다시 확인.

문제:

```text
AI를 오래 사용해도
이전 학습 맥락과 사고 패턴을 충분히 기억하지 못함
```

따라서:

```text
장기 데이터
+
사용자의 사고 과정
+
시간에 따른 변화
```

를 누적하는 시스템이라는 정체성이 강화됨.

---

## 2026-09-16 21:32 · PIVOT

Teacher Agent 목적이 달라짐.

기존:

```text
시험 문제 예측
```

중심에서:

```text
교사가 반복해서 강조하는 것
교사가 중요하게 판단하는 것
교사가 요구하는 사고 과정
교사가 채점할 때 보는 기준
```

을 발견하는 방향으로 이동.

또한 적은 자료 하나로 교사를 단정하면 안 된다고 판단.

초기 Teacher Model은 최소 한 학기 정도의 evidence를 기반으로 하는 **가설**로 취급하기로 함.

---

## 2026-09-16 21:52 · DESIGN

전체 폐쇄 루프:

```text
Teacher Agent
     ↓
Student Agent
     ↓
Coach Agent
     ↓
학생 행동
     ↓
실제 결과
     ↓
다시 Student/Teacher state 업데이트
```

Teacher Agent부터 MVP를 만드는 방향으로 결정.

---

# 2026년 9월 17일 — Teacher Reasoning 분석 시작

## 2026-09-17 18:56 · DESIGN

Backspace가 참고할 장기 자료 범위를 확장.

```text
Chat
문서
Notion
Google Drive
```

등을 장기 분석 대상으로 고려.

교사 수업 녹취 분석도 본격적으로 진행.

생명과학 교사의 반복 사고 구조가 추출됨.

```text
결과 관찰
→ 필연적 조건 확인
→ 원인 / 구조 역추론
→ 조건 변경으로 검증
→ 결론
```

이후 Teacher Model 설계의 실제 사례가 됨.

---

# 2026년 9월 22일 — 최초 수동 Backspace 시뮬레이션

## 2026-09-22 · VALIDATED

초기 Backspace 모델을 실제 공부/시험 데이터에 수동 적용.

이 시점에는 완성된 프로그램이라기보다:

```text
교사 특성
학생 오답
인출 상태
학습 행동
시험 결과
```

을 하나의 모델로 연결하는 실험에 가까웠음.

---

# 2026년 9월 27일 — Student State / Behavior Model

## 2026-09-27 11:53 · DESIGN

Backspace v0.1 형태가 구체화.

```text
Student State / Behavior Model

예측
↓
실제 결과
↓
오차 분석
↓
모델 업데이트
```

과목별 사고 구조도 따로 보기 시작함.

예:

```text
화학
상태
→ 조건
→ 불변량 / 남은 종
→ 공식
→ 계산

물리
접점 / 불변량 판단

생명
Teacher Model

지구
관계망

정보
탐색량 축소
```

하나의 범용 학습법으로 모든 과목을 처리하는 것은 어렵다는 점이 드러남.

---

## 2026-09-27 18:59 · VALIDATED

시험 결과/등수와 Backspace 판단을 연결하는 실험.

예측에는 단순 숫자 하나가 아니라:

```text
예상 범위
불확실성
근거
다음 행동
```

을 같이 제공해야 한다는 원칙이 생김.

---

# 2026년 10월 2일 — MVP 다시 축소

## 2026-10-02 14:09 · PIVOT

Backspace의 범위가 여전히 너무 크다고 판단.

다른 사업 아이디어와 비교했지만 Backspace를 계속 진행하기로 함.

---

## 2026-10-02 14:12 · IDEA

MVP를 다음처럼 재정의.

> 학생이 무엇을 틀렸는지가 아니라 왜 그렇게 생각했는지를 기억하는 AI

흐름:

```text
문제
↓
학생 풀이 과정
↓
사고 오류 분석
↓
Thinking Memory
↓
다음 문제에서 피드백
```

Memory가 단순 학습 기록이 아니라 **사고 과정의 장기 기억**으로 자리 잡음.

---

## 2026-10-02 14:23 · PRODUCT

Backspace 미팅 준비 및 PPT 제작 시작.

이 시기 Backspace가 `모두의 창업` 예비선정을 통과하면서 프로젝트의 상황이 급변함.

---

# 2026년 10월 4일 — Teacher Agent MVP 확정

## 2026-10-04 12:00 · PIVOT

Teacher Agent를 MVP의 중심으로 결정.

입력:

```text
기존 시험지
수업자료
수업 녹취
```

출력:

```text
교사의 사고 방식
출제 방식
평가 기준
채점 방식
```

---

## 2026-10-04 12:16 · PRODUCT

Backspace 예비선정 이후:

```text
언젠가 만들 프로젝트
```

에서

```text
지금 실제 결과물을 보여줘야 하는 메인 프로젝트
```

로 상태가 변경됨.

---

## 2026-10-04 12:56 · DESIGN

Teacher Agent MVP:

```text
수업 녹취
+
기존 시험지
+
수업 자료
       ↓
Teacher Model
       ↓
이 선생님의 기준으로 답안 평가
       +
이 선생님 스타일에 맞는 연습
```

개인별 Teacher Model이 핵심 차별점으로 정리됨.

---

# 2026년 10월 6일 — 현재 Backspace 철학 확정

## 2026-10-06 18:40 · PRODUCT

Backspace를 다음처럼 다시 정의.

> 내가 무엇을 알고 무엇을 모르는지를 이해하게 해주는 자아성찰형 개인 AI 학습 파트너

주요 경험 흐름:

```text
대화 / 학습
↓
현재 이해 상태
↓
약한 부분 발견
↓
질문 / 힌트
↓
다시 사고
↓
개인 모델 갱신
```

---

# 2026년 10월 6일 ~ 7일 — JSON 중심 Teacher 분석의 한계

## 2026-10-07 오전 · FAILURE

기존 구조:

```text
PDF
↓
OCR
↓
큰 구조화 JSON
↓
Graph
↓
Pattern
↓
Teacher Model
```

에서 NVIDIA Nemotron이 긴 구조 분석을 처리하며 반복적으로 실패.

대표 오류:

```text
output_limit
timeout
```

특히:

```text
nvidia/nemotron-3-super-120b-a12b
```

의 긴 structured output이 병목이 됨.

단순 모델 교체로 해결되지 않는다고 판단.

---

# Text-first 전환

## 2026-10-07 오전 · PIVOT

핵심 발상 전환:

```text
자료를 이해한다
≠
거대한 JSON을 만든다
```

따라서:

```text
원문
↓
자연어 Understanding Note
↓
Memory
↓
필요할 때만 구조화
```

방식으로 이동.

핵심 개념:

```text
Text = 원자재
Topic = 조직 구조
Summary = 파생물
Teacher Model = 최종 추론
```

---

# A-MEM 선택

## 2026-10-07 오전 · DESIGN

여러 Memory/RAG framework를 동시에 섞지 않고 **A-MEM 하나를 먼저 실제 기반으로 사용**하기로 결정.

선택 upstream:

```text
agiresearch/A-mem
```

핵심:

```text
MemoryNote
AgenticMemorySystem
Chroma retrieval
memory linking
metadata evolution
```

을 최대한 실제 upstream 코드 기반으로 사용.

---

# 2026-10-07 13:17 — A-MEM 통합 완료

## IMPLEMENTED

A-MEM 기반 자료 이해 메모리가 Backspace에 통합됨.

고정 upstream commit:

```text
ceffb860f0712bbae97b184d440df62bc910ca8d
```

새 흐름:

```text
OCR cache
↓
자연어 Understanding Note
↓
A-MEM MemoryNote
↓
Persistent Chroma
↓
related note linking
↓
secondary graph
↓
Teacher Model
```

기존 기능은 유지:

```text
OCR
Graph
Jev
Teacher Model
Planning
원문 quote validation
```

---

## IMPLEMENTED — A-MEM Adapter

추가 변경:

```text
persistent Chroma
NVIDIA metadata adapter
Topic namespace
source provenance
checkpoint
rejected-note state
```

A-MEM 원본의 collection reset/OpenAI initialization 문제를 adapter로 우회.

---

## IMPLEMENTED — Embedding

PyTorch `c10.dll` 정책 문제로 sentence-transformers 기본 실행이 어려워짐.

대안:

```text
paraphrase-multilingual-MiniLM-L12-v2
ONNX
384 dimensions
normalized embedding
```

사용.

---

## VALIDATED

Python 테스트:

```text
112 passed
```

기존 104 regression + A-MEM 8 tests.

검증한 것:

```text
note persistence
restart restore
topic
linking
neighbor update
Teacher context integration
graph failure reuse
partial ranges
rejected note exclusion
body immutability
```

---

# p6 실자료 성공

## 2026-10-07 13:17 · VALIDATED

실제 생명과학 PDF p6:

```text
(3) 02. 기관계의 통합적 작용~
```

검증.

결과:

```text
Understanding Note 생성
4.203 sec

NVIDIA calls
2

Chroma search
성공

restart reuse
성공

원 PDF hash
변화 없음
```

---

# p7 표 해석 실패

## 2026-10-07 13:17 · FAILURE

p7에서 표 구조를 잘못 해석.

예:

```text
albumin
→ 지방 검출 시약으로 잘못 해석
```

secondary graph도 timeout 발생.

결론:

```text
A-MEM 문제 X
Teacher Model 문제 X

Perception / table reconstruction 문제 O
```

잘못된 Understanding Note는 삭제하지 않고:

```text
rejected
```

처리하여 Teacher evidence에서 제외.

---

# Embedding truncation 문제 발견

## 2026-10-07 13:17 · DESIGN

현재 embedding max token:

```text
128
```

반면 Understanding Note source unit은 최대 약:

```text
1800 chars
```

따라서 note 뒤쪽 의미가 embedding에 반영되지 않을 위험 발견.

향후 원칙:

```text
Memory unit
≠
Embedding unit
```

하나의 note를 여러 embedding chunk로 인덱싱하는 방안 제안.

---

# 2026-10-07 14:18 — Jev Semantic Control Plane 구현

## IMPLEMENTED

Jev 역할을 최종 scoring에서 시스템 제어까지 확대.

기존:

```text
Understanding
↓
NVIDIA
↓
Graph
↓
Teacher
↓
Jev score
```

변경:

```text
Understanding Note
↓
A-MEM
↓
Jev
↓
필요한 경우만 NVIDIA
```

Jev 판단:

```text
topic
duplicate
relation
teacher signal
exam relevance
needs slow reasoning
graph needed
```

같은 state에 대한 질문은 **한 request에 batch**.

---

## IMPLEMENTED — Graph Gate

모든 Understanding Note를 graph로 만들지 않음.

Jev가:

```text
새로운 관계가 있는가?
Teacher Model에 영향을 주는가?
평가 사고 구조가 있는가?
```

판단.

필요성이 낮으면 note만 저장.

---

## IMPLEMENTED — Teacher Hypothesis Validation

Teacher 가설과 evidence 관계를:

```text
supports
contradicts
insufficient
irrelevant
```

로 분리.

특히:

```text
지지하지 않음
≠
반박
```

원칙을 코드 구조에 반영.

---

## VALIDATED

p6 동일 자료 재처리.

기존:

```text
NVIDIA calls = 2
NVIDIA wait = 36.984 sec
```

새 구조:

```text
Jev calls = 1
Jev wait = 0.297 sec
additional NVIDIA calls = 0
```

Jev 판단:

```text
기존 설명을 강화
slow reasoning 불필요
graph는 필요
```

---

## VALIDATED

Python tests:

```text
128 passed
```

새 16 tests:

```text
duplicate
novel
contradiction
graph skip
hypothesis support
irrelevant
Jev failure
resume
low confidence
```

등 검증.

---

# A-MEM Metadata NVIDIA 의존성 발견

## 2026-10-07 14시대 · FAILURE

Understanding Note 생성은 성공했지만 이후:

```text
A-MEM metadata generation
```

단계가 NVIDIA를 다시 호출.

실패:

```text
nemotron-3.5-lightning-30b-a3b
network_error
1.203 sec

nemotron-3-super-120b-a12b
network_error
38.922 sec
```

결과:

```text
자연어 note는 보존
하지만 전체 pipeline은 실패 표시
```

---

## PIVOT

A-MEM metadata에서 NVIDIA 의존성을 제거하는 방향 결정.

새 원칙:

```text
Understanding Note
↓
즉시 저장
↓
local metadata
↓
A-MEM retrieval
↓
Jev relation decisions
```

즉:

```text
keywords
tags
topic
duplicate
relation
```

등을 위해 대형 reasoning LLM을 호출하지 않는 방향.

---

# Teacher Model 자체도 Jev 중심으로 변경

## 2026-10-07 14~15시 · DESIGN

GitHub Jev 프로젝트 조사 후 새로운 구조 결정.

Teacher Model을:

```text
NVIDIA가 한 번에 만들어내는 JSON
```

이 아니라:

```text
evidence
+
Jev typed decisions
+
Python state update
```

의 누적 결과로 취급.

---

## TeacherModelUpdateEngine 설계

새 evidence와 기존 hypothesis 관계:

```text
reinforces
weakens
contradicts
narrows_scope
broadens_scope
unrelated
insufficient
```

를 Jev가 판단.

Python이 실제 모델 상태 수정.

새로운 teacher-specific meaning이 필요한 경우에만 NVIDIA 호출.

---

## EvidenceRelation 도입

Teacher Model을 설명 가능하게 만들기 위해:

```text
Evidence
↔
Hypothesis
```

관계를 first-class data로 저장하는 방향 확정.

---

# 2026-10-07 15:28 — 작은 구간까지 실패

## FAILURE

UI 메시지:

```text
작은 자료 구간도 분석을 완료하지 못했습니다.
보존된 원문·이해 노트를 검토하세요.
```

하지만:

```text
9개 자료의 텍스트·이미지 읽기
완료
```

즉 이미 상당 부분이 성공했는데 후단 오류 하나가 **전체 실패**로 표시되고 있었음.

---

# Partial Success Pipeline 결정

## 2026-10-07 15:31 · PIVOT

핵심 성공 조건을 변경.

기존:

```text
OCR
+ Understanding
+ Memory
+ Graph
+ Teacher
전부 성공
=
job success
```

변경:

```text
Understanding Note 저장
=
Material ingest success
```

그 이후:

```text
Memory enrichment
Jev
Graph
Teacher update
Planning
```

은 독립적이고 재개 가능한 downstream stage.

---

## Stage State 설계

```text
PERCEPTION
UNDERSTANDING
MEMORY_PERSIST
MEMORY_ENRICHMENT
JEV_ROUTING
GRAPH_PROJECTION
PATTERN_MINING
TEACHER_UPDATE
TEACHER_SYNTHESIS
PLANNING
```

상태:

```text
not_started
running
complete
skipped
pending
failed_retryable
failed_terminal
rejected
```

전체 결과도:

```text
complete
partial_success
needs_review
failed_before_understanding
```

으로 세분화.

---

# 2026-10-07 오후 — Partial Success 실제 반영

## IMPLEMENTED / VALIDATED

후속 화면에서 단계별 상태가 실제로 표시됨.

```text
기본 메모리 저장
119 / 119 ✓

메모리 검색·연결
135 / 135 ✓

이해 노트 저장
127 / 127 ✓

Jev 판단
134 / 134 ✓

텍스트·이미지 읽기
8 / 8 ✓

개념·사고 지도
1 / 9 △

교사 근거 갱신
9 / 9 ✓

새 교사 가설
1 / 1 ✓

반복 패턴
1 / 1 ✓
```

즉 이전과 달리 graph가 실패해도:

```text
Memory
Understanding
Jev
Teacher evidence
```

가 성공 상태로 남게 됨.

Partial-success architecture가 실제 UI 상태로 나타나기 시작.

---

# 2026-10-07 20:15 — 병목이 Graph/Perception으로 이동

## FAILURE

남은 주요 실패가 `개념·사고 지도`에 집중됨.

상태:

```text
Graph
1 / 9
```

재시도 필요:

```text
4건
```

검토 필요:

```text
4건
```

---

## FAILURE — Structured generation

NVIDIA:

```text
schema_invalid
11.86 sec
```

또는:

```text
invalid_json
16.047 sec
```

발생.

즉 Graph 단계가 아직 구조화 JSON 생성에 의존하면서 failure point로 남아 있음.

---

## FAILURE — Quote validation

실제 오류:

```text
개념 '생명과학':
quote가 원문에 없습니다.

개념 '생태계':
quote가 원문에 없습니다.
```

원인 후보가:

```text
LLM hallucinated quote
OCR 오인식
손글씨 인식 실패
normalized text 차이
```

등으로 좁혀짐.

---

# 2026-10-07 20:16 — 한국어 필기체 OCR 조사

## RESEARCH

GitHub에서 한국어 handwriting OCR 후보 조사.

주요 후보:

```text
jysvai/ko-hand-ocr
apphia39/pghj-kocrnn
jkf87/korean-handwriting-ocr-benchmark
```

---

# ko-hand-ocr 선택

## 2026-10-07 20:19 · DESIGN

Backspace에 가장 적합한 후보:

```text
https://github.com/jysvai/ko-hand-ocr
```

선정.

이유:

```text
한국어 손글씨 한 줄 OCR
한글 + 영문 혼합
ViT + TrOCR
41M
Apache-2.0
CPU 가능
사진 line segmentation 지원
최근 유지보수
```

---

# Handwriting fallback architecture 확정

## 2026-10-07 20:19 · DESIGN

PaddleOCR는 제거하지 않음.

새 구조:

```text
Native Text
       ↓
PaddleOCR
       ↓
OCR quality / handwriting 판단
       │
       ├─ 일반 인쇄체
       │      ↓
       │  Paddle 유지
       │
       └─ 손글씨 / 저신뢰
              ↓
        ko-hand-ocr
              ↓
       candidate comparison
              ↓
      trusted transcription
```

---

## Table 역할 분리

중요 원칙:

```text
Layout understanding
≠
Character recognition
```

따라서:

```text
표 구조 / 행 / 열
→ 기존 layout/Paddle

셀 안의 손글씨
→ ko-hand-ocr
```

로 분리.

p7의 albumin 오류 같은 table reconstruction 문제를 handwriting OCR이 자동으로 해결한다고 가정하지 않음.

---

# 현재 Backspace 구조 — 2026-10-07

현재까지의 변화를 하나로 합치면:

```text
PDF / PPT / Image
        ↓
Perception
Native + Paddle + Visual
        ↓
[Handwriting fallback 예정]
ko-hand-ocr
        ↓
Normalized Source
        ↓
NVIDIA
Understanding Note
        ↓
──────────────────
Material ingest commit
──────────────────
        ↓
A-MEM
Persistent Memory
        ↓
Semantic Retrieval
        ↓
Jev Control Plane
        │
        ├ duplicate
        ├ relation
        ├ topic
        ├ teacher signal
        ├ graph needed
        └ slow reasoning needed
        ↓
Python state update
        ↓
필요한 경우만 NVIDIA
        ↓
Secondary Graph
        ↓
Pattern Mining
        ↓
Teacher Model Update
        │
        ├ EvidenceRelation
        ├ support
        ├ contradiction
        ├ scope
        └ candidate hypothesis
        ↓
Jev Validation
        ↓
Teacher Model State
        ↓
Planning
```

---

# Backspace 변화의 큰 흐름

## 1세대 — 성적관리 AI

```text
성적
시험
Notion
→ AI 관리
```

---

## 2세대 — 나를 기억하는 AI

```text
장기 기억
습관
오답
패턴
→ 개인 모델
```

---

## 3세대 — 사고 과정 AI

```text
왜 그렇게 생각했는가?
→ Thinking Memory
```

---

## 4세대 — Teacher Agent

```text
자료 + 기출 + 수업
→ 교사의 평가 사고 모델
```

---

## 5세대 — JSON-first Teacher Model

```text
OCR
→ 구조화 JSON
→ Graph
→ Pattern
→ Teacher Model
```

문제:

```text
output_limit
timeout
schema failure
```

---

## 6세대 — Text-first / A-MEM

```text
OCR
→ Understanding Note
→ Memory
→ 필요 시 구조화
```

핵심 전환:

> 이해를 먼저 하고 구조화는 나중에 한다.

---

## 7세대 — Jev Semantic Control Plane

```text
FAST typed decisions
→ 필요한 경우에만 slow reasoning
```

NVIDIA 호출을 gate하는 구조 도입.

---

## 8세대 — Incremental Teacher Model

```text
Evidence
→ Jev relation
→ Python update
→ Teacher Model state
```

전체 모델을 매번 재생성하지 않는 방향.

---

## 9세대 — Partial Success Pipeline

```text
Understanding 저장 성공
=
자료 이해 성공
```

후단 오류를:

```text
pending
retryable
review
```

로 분리.

---

## 10세대 — OCR Specialization

현재 진행 단계.

```text
PaddleOCR
+
ko-hand-ocr
+
layout parser
```

를 역할별로 분리해:

```text
인쇄체
손글씨
표 구조
```

를 각각 적합한 recognizer가 담당하도록 변경 중.

---

# 현재 가장 큰 병목

2026-10-07 기준:

```text
Memory           ✓
Understanding    ✓
Jev              ✓
Teacher Evidence ✓
Teacher Hypothesis ✓

Graph / Concept Map △
Perception/OCR    △
```

즉 처음에는:

```text
Teacher Model 생성
```

이 가장 큰 문제였지만,

A-MEM과 Jev를 도입한 이후 병목이 앞으로 이동해 현재는:

```text
원문 인식 정확도
↓
표 구조 복원
↓
quote provenance
↓
secondary graph structured generation
```

으로 이동했다.

이것은 중요한 변화다.

현재 Backspace는 더 이상:

```text
"Teacher Model이 안 만들어져서 막히는 프로그램"
```

보다는:

```text
"좋은 memory와 Teacher state는 만들 수 있지만,
그 앞단 perception과 일부 graph projection의 신뢰도가 부족한 프로그램"
```

에 가까워졌다.

---

# 다음 변천사 기준점

다음부터 코드 변경이 발생할 때는 최소 아래 형식으로 기록하면 된다.

```text
YYYY-MM-DD HH:MM KST

TYPE:
IMPLEMENTED / FAILURE / PIVOT / VALIDATED

MODULE:
Perception / Memory / Jev / Graph / Teacher / Planner

CHANGE:
무엇을 바꿨는가

WHY:
왜 바꿨는가

BEFORE:
이전 구조

AFTER:
새 구조

RESULT:
tests / latency / failures / benchmark

NEXT:
다음 문제
```

예:

```text
2026-10-07 20:19 KST

TYPE
DESIGN

MODULE
Perception

CHANGE
ko-hand-ocr를 한국어 손글씨 fallback으로 선택

WHY
quote validation failure 및 한국어 필기 OCR 정확도 문제

BEFORE
Native + PaddleOCR

AFTER
Native + PaddleOCR
→ handwriting/low-confidence region
→ ko-hand-ocr

NEXT
20~30개 biology region CER benchmark
```

이 형식을 앞으로 계속 append하면 Backspace 자체의 **개발 진화 기록**이 된다.