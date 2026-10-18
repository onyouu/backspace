# 증분 Teacher Model 구현 상세

## 기존/변경 흐름

기존: OCR/검토 → 이해 노트/A-MEM → 자료·문항 그래프 → Python 반복 패턴 → NVIDIA 가설 묶음 → Jev 점수 → Python 모델 조립 → 계획.

변경: 위 입력 처리 유지 → 변경된 근거 찾기 → 개념·사고 코드로 관련 가설 후보 제한 + 저장된 A-MEM 조회 → Jev 관계 5문항 묶음 → Python 개별 상태 변경 → 반복 근거 묶음 prefilter/novelty gate → 필요할 때만 NVIDIA 후보 1개 → Jev integration gate → Python 후보 저장/승격 → 기존 개념 6차원 점수 → 기존 모델 JSON 조립 → 계획.

전체 모델 JSON 생성에 쓰이던 NVIDIA 호출을 제거했다고 표현하면 부정확하다. 그 호출은 원래 없었고, 자동 가설 묶음 생성을 조건부 단일 후보 생성으로 교체했다. OCR/Understanding/Graph 의미 해석 및 선택적 자연어 계획은 NVIDIA를 계속 사용한다.

## 코드 위치

- `backspace_mvp/teacher_update.py:TeacherModelUpdateEngine`: 관계 저장, 카운트·비율·가중치·상태·범위 후보, 후보 통합, 피드백, 프로세스 간 파일 잠금, 원자적 체크포인트.
- `teacher_incremental.py:update_teacher_model`: 기본 경로 연결, 검증된 근거 catalog, 변경된 쌍만 처리, 완전한 문항 묶음 구성, 기존 artifacts와 점수/모델 builder 연결.
- `teacher_questions.py`: 버전이 있는 Jev 독립 질문. `SemanticControl`의 혼합 타입 요청/확률·confidence 검증과 캐시 사용.
- `schemas/evidence_relation.schema.json`, `schemas/teacher_update.schema.json`: 관계/델타 계약.
- `web.py`: `teacher` 작업의 기본 경로 교체, 부분 완료/대기 안내. `cli.py`: 증분 명령·수동 재생성·피드백 명령.
- `study_plan.py:_teacher_context`: 증분 가설은 active만 전달하고 범위 후보 확인 대기를 제외한다. legacy lifecycle 없는 모델은 기존 동작 유지.

## Jev 질문과 버전

| 번들 버전 | 질문 | 타입 |
|---|---|---|
| `teacher-relation-v1` | relation: reinforces/weakens/contradicts/narrows_scope/broadens_scope/unrelated/insufficient | Choice |
| 같은 번들 | strength: incidental/limited/substantial/strong direct, 0–3 | Score |
| 같은 번들 | scope: single_question/question_type/topic/unit/cross_unit/global/insufficient | Choice |
| 같은 번들 | novel_pattern, needs_slow_reasoning | Noul 각각 |
| `teacher-prefilter-v1` | teacher_signal, generic_subject_knowledge | Noul 각각 |
| 같은 번들 | 전체와 각 evidence의 relevance/novelty 0–2 | Score 각각 |
| `teacher-novelty-v1` | novel_pattern, needs_slow_reasoning | Noul 각각 |
| 같은 번들 | closest: 제한된 기존 가설/none/insufficient | Choice |
| `candidate-integration-v1` | duplicate_existing/subtype_of_existing/broader_than_existing/new_independent/contradicts_existing/insufficient | Choice |
| 같은 번들 | closest, sufficient | Choice / Noul |
| `teacher-sufficient-v1` | 현재 조건에서 잠정적으로 안정적이라고 볼 충분한 근거인가 | Noul |

같은 상태의 독립 질문을 한 요청으로 보낸다. 각 질문의 실제 state 경로를 문장에 넣으며, 다른 질문의 응답을 참조하지 않는다. 요청 기록에 질문 원문/해시, 번들 버전, 개별 `question_versions`, 원 응답, 모델, 확률, 별도 confidence를 저장한다. 문구가 바뀌면 버전을 올린다. 기존 state의 버전과 다르면 자동 재해석하지 않는다.

기본 Noul yes ≥ .8 / no ≤ .2. Choice selected probability ≥ .8 및 confidence ≥ .65. Strength confidence ≥ .65. 관계 판단에 필요한 범위/강도가 불확실하면 pending_review. 무관 판정에는 scope=insufficient가 허용되며 가설에 영향이 없다. Noul에는 별도 confidence를 만들지 않는다. Score는 확률이 아니라 rubric 위치이며 원 분포도 보존한다. [공식 API](https://docs.typesafe.ai/api), [Noul](https://docs.typesafe.ai/primitives/noul), [Confidence](https://docs.typesafe.ai/confidence).

## 저장 계약과 재실행

`dataset` 옆에 기존 `teacher_model.json`을 유지하며, `teacher_model/` 디렉터리에 독립 상태를 추가한다.

```text
teacher_model/
  state.json             # 전체 복사가 아닌 최신 원자적 트랜잭션 체크포인트
  writer.lock            # 프로세스 종료 시 OS 잠금 해제
  hypotheses/<id>.json   # 독립 가설의 현재 상태
  relations/<hash>.json   # EvidenceRelation
  evidence/<hash>.json    # 정확한 인용/위치/출처
  evidence_history/      # 원자료가 바뀐 이전 근거
  updates/<hash>.json     # 상태 변경 delta
  decisions/<kind>/      # Jev 원 판단·상태·질문 버전
  decisions/<kind>/attempt_history/ # 실패 재시도 전 기록
  candidates/            # 제안된 후보 기록
  pending/               # 판단/생성/통합 대기
  versions/v<n>.json     # 버전·state hash·delta ID 목록
  feedback/              # 사람/시험 피드백
```

relation은 Python의 적용 가능 상태이며, 범위 판단이 불확실하면 insufficient/pending_review로 보류한다. 원 Jev의 선택은 raw_relation과 원 decision에 별도로 남기므로 지지 판단을 실패로 바꾸거나 잃지 않는다. jev_probability/confidence는 이 원 선택에 대한 값이다.

EvidenceRelation: evidence_id, evidence_hash, hypothesis_id, relation, strength, scope, raw_relation, jev_probability, jev_confidence, question_version(s), jev_decision_id, created_at, status, provenance, coverage.

Delta: update_id, teacher_model_version_before/after, evidence_id, hypothesis_id, jev_decision_id, action, previous_state, new_state, created_at.

캐시 식별자는 근거의 원문/의미 구조 해시 + 가설 ID·문장·범위 + 질문/정책/임계값 버전이다. 문맥별 `matching_pattern_ids` 변화는 새로운 원문 관찰로 세지 않는다. 동일 witness를 질문 버전마다 두 번 세지 않는다. NVIDIA 생성 성공 결과는 통합 판단 전에 checkpoint에 저장하여 Jev 통합 실패 후 재생성하지 않는다.

state.json 저장 완료 후 개별 파일을 투영한다. 중간 종료로 파일이 없거나 손상되면 체크포인트에서 복구한다. canonical 상태 해시가 손상되면 멈추며 원본을 덮어쓰지 않는다. 원자료 변경/제거는 현재 통계에서 제외하되 이전 관계/가설/델타를 보존한다.

## 문맥·승격·점수 정책

기본: 관련 가설 최대 4개, 변경 근거 최대 24개/실행, 반복 묶음 최대 3개/실행, 완전한 문항 최대 4개, 자료 항목 최대 2개, 생성 문맥 15,000자. 큰 묶음은 3/2개의 완전한 문항 및 1/0개의 자료 항목으로 줄이며 문장이나 원문 구절은 자르지 않는다. 생성 입력에 들어갈 선택적 메모리도 전체 노트 단위로만 제외한다.

반복 node/edge/path가 같은 witness 집합을 가질 때 중복 synthesis하지 않는다. prefilter에서는 teacher_signal과 generic_subject_knowledge를 독립적으로 판단한다. generic=True만으로 제외하지 않는다. Python이 mandatory 원문 문항/반례를 우선하고, relevance·novelty 점수로 나머지 순서를 구성한다. 이미 알려진 반례가 제한 문맥에서 빠지면 생성하지 않고 검토 대기를 남긴다. 선택/전체 범위는 모델·결정 기록에 표시한다.

support/counter count, 독립 문항 수, source diversity(원자료 SHA), support/contradiction ratio, strength/3의 합계와 ranking weight는 Python이 계산한다. 관계 비율/합은 teacher preference의 진실 확률이 아니다. 활성화에는 Jev sufficient + 독립 문항/원자료 각각 2개 이상 + 충분한 검토 범위 + 미해결 강한 반박 부재 + 범위 검토 완료를 요구한다. 단일 자료의 반복 요약은 독립 자료로 세지 않는다. 이 stopping은 모든 새 근거의 처리를 중단하는 기능이 아니라 추가 가설 synthesis의 필요성을 줄이는 상태다.

기존 `build_teacher_scores`의 개념 6차원과 요청 캐시를 계속 사용한다. 기본 경로에서는 가설에 대한 전체 근거 재점수화 대신 새 관계 판단/상태 계산을 사용한다(`max_hypotheses=0`). 이전 가설 점수는 sidecar legacy/history에 보존되고 수동 점수 명령도 유지된다. 개념 점수 실패는 미산정 및 pending_concept_ids로 표시하며 이전 점수를 현재 점수로 가장하지 않는다.

## 실패/재생성/피드백

Jev 오류/낮은 확신 → 근거와 raw 판단 보존, pending_review. NVIDIA 새 후보 오류 → candidate_generation_pending, 다른 성공 갱신 유지. 큰 문맥 → 제한된 완전한 묶음으로 감소하거나 검토 대기. 동일 큰 요청의 timeout 상향은 없다. A-MEM metadata/evolution 실패 → 이미 작성한 제목/주제로 로컬 metadata 및 기존 본문/연결 유지. 검색 장애 → canonical 본문/출처·hash 검증 후 제한적 fallback; 거절/오래된 노트는 제외한다.

`update_teacher_model --manual-rebuild` 및 기존 세 CLI 단계는 명시적 수동 전체 생성 경로다. 새 schema/question/policy migration과 canonical corruption recovery는 자동 초기화하지 않는다. 이전 state를 보존하는 별도 명시적 마이그레이션/복구가 필요하며, 이 명령이 임의로 손상된 state를 지우지 않는다. 큰 미해결 반박은 contested/pending에서 사람 검토 후 명시적 재생성을 선택한다. benchmark도 별도 디렉터리에서 명시적으로 실행한다.

피드백 종류: human_confirmed/human_rejected/human_narrowed_scope/observed_in_exam/not_observed_in_exam/contradicted_by_exam. 동일 event ID 재실행은 중복 저장하지 않으며, 다른 내용으로 덮어쓸 수 없다. 기존 Jev decision IDs와 당시 상태 버전을 같이 남긴다. 확인됐다는 피드백 하나로 근거 최소 조건을 우회하지 않는다. 부재(not_observed)를 반박으로 자동 변환하지 않는다. 보정 학습·beam search·계획 자동 delta는 extension point다.

## 검증 기록

`tests/test_teacher_update.py`: A–I, 낮은 확신, 원자료 제거/변경, 승격 조건, 피드백 불변성, 부분 저장 복구, 상태 손상 방어, 원문 인용 검증, legacy/증분/계획 호환, 파이프라인 부분 실패, 문맥 패턴 변화 재실행. `tests/test_web.py`는 새 기본 경로와 명시적 수동 경로 모두 모의 API로 검증한다.

전체 152 tests 통과. 증분 갱신 23개와 A-MEM 부가 정보의 네트워크 장애 테스트 1개를 새로 추가했다. 마지막 관계 기록 필드 변경 후 해당 증분 검사 23개도 통과했다. npm check의 문법/지도/모션 회귀도 통과했다.

실제 자료 검증: `scripts/validate_teacher_incremental.py --live --out <독립 폴더>`. 공식 API 실제 호출 결과는 `output/teacher_incremental_validation/live/benchmark.json` 및 결정/usage 기록에 있다. 원 PDF SHA·저장 노트 본문 hash 확인. 실제 모델 3–5개가 존재하지 않아 **새 잠정 probe 3개**를 사용한 제한된 관계 비교다. 기존 전체 Teacher Model rebuild benchmark로 주장하지 않는다. 비교 대조는 작은 NVIDIA 재해석 요청 1건(실제 2회 시도, 첫 응답 JSON 실패)이며 증분은 Jev 6건이다. 관련 3건은 범위 confidence가 낮아 pending, 무관 3건은 unrelated, 가설 갱신 0건, 재실행 API/델타 증가 0이다. 허위 반박/허위 무관 0은 수작업으로 지정한 이 작은 relevance 대조 범위만 해당한다.

다음 검증 후보는 완성된 실제 모델 3–5개와 여러 시험의 추가 근거, 적용 범위 질문의 검토 대기율, 단원/문항형식별 사람 판단 일치도, 이후 피드백 기반 calibration이다.
