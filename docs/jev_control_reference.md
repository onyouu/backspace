# Jev Semantic Control 구현 기록

사용자용 내용 보고서는 [jev_control_update.md](jev_control_update.md), 수정 전 호출 지도는 [jev_call_mapping.md](jev_call_mapping.md)다. 기존 A-MEM의 원본 메서드를 재작성하지 않고 Backspace 어댑터에서 제어한다.

## 실제 연결한 위치

| 위치 | 판단·처리 | 유지되는 LLM 작업 |
|---|---|---|
| `UnderstandingWorkspace.ingest_source` | 자연어 노트 이후 현재 버전·거절되지 않은 A-MEM 관련 노트 최대 3개 검색, 9개 독립 질문을 한 요청에 묶음 | 원문·선택 이미지에서 새로운 자연어 이해 노트 생성 |
| `NvidiaMemoryController` | 확실한 기존 의미는 저장된 keywords/context/tags 복사와 검증된 관련 노트 링크만 갱신 | 새로운 의미·충돌·불확실성의 metadata/evolution 해석 |
| `StagedExtractor.pages` | 같은 번들 안의 3개 graph 질문을 사용. 모두 명확히 낮을 때만 자료 그래프 생략 | 필요한 자료 개념·관계 추출 및 의미 검토; 시험 문항 분석은 생략하지 않음 |
| `build_teacher_hypotheses` | 생성 후 가설별 4개 typed 질문을 한 요청에 묶음; 원 근거 registry를 유지 | 새 조건부 교사 가설 생성 |
| `build_teacher_model` | 가설 검증 결과를 보존하고 검토 우선순위에 반영 | 기존 Python 조립·빈도 계산·v0.5 scoring 유지; 이 함수 자체는 NVIDIA를 부르지 않음 |

노트 분류와 graph gate는 같은 state를 사용하므로 Jev 요청은 **노트당 1개**, graph audit은 번들의 참조 기록이다. 가설 검증은 가설당 1개다. 조회·검색은 API를 부르지 않는다. 새 자료의 노트 본문 생성은 생략하지 않는다.

## 질문과 응답

`backspace_mvp/jev_questions.py`에서 문구를 관리한다.

| 번들 | 버전 | 질문 |
|---|---|---|
| Note Router + Graph | `note-router-2` | topic Choice, duplicate Noul, relation Choice, teacher_signal Noul, exam_related Noul, needs_slow_reasoning Noul, graph_relation / graph_teacher / graph_assessment Noul |
| Hypothesis Validation | `hypothesis-validation-2` | relation Choice(supports/contradicts/insufficient/irrelevant), strength Score(0..3), scope Choice(global/unit_specific/question_type_specific/single_case/insufficient), reanalysis Noul |
| 예약된 확장 계약 | `future-gates-1` | hypothesis_prefilter, teacher_update_gate, planning_gate(no_change/local_adjustment/full_replan) |

정확한 계약은 [공식 HTTP API](https://docs.typesafe.ai/api), [Noul](https://docs.typesafe.ai/primitives/noul), [confidence](https://docs.typesafe.ai/confidence)를 따른다. Noul에는 별도 confidence가 없다. 따라서 audit의 해당 confidence는 null이며 Noul 원값을 probabilities에 보존한다. Choice/Score의 probabilities와 confidence를 별도로 저장한다. Score는 기준표상 위치이며 중요도·가설 확률로 변환하지 않는다.

후속 가설 artifact의 `jev_validation`은 decision ID, 실제 모델, evidence_relation, summary_status, scope, strength_score / strength_confidence, needs_reanalysis를 담는다. 전체 원답·분포는 audit에 남긴다. 적용 범위가 불확실해도 분명한 evidence_relation을 따로 보존한다. 원래의 교사 가설·대안 설명·반례·지원 문항 수는 삭제하지 않는다.

## 설정

키는 기존 `.env`의 `TYPESAFE_API_KEY`, NVIDIA 키는 기존 환경 설정을 그대로 사용한다. 실제 `.env`와 사용자가 제공한 키 파일을 변경하지 않았다.

```dotenv
BACKSPACE_JEV_CONTROL_ENABLED=1
JEV_MODEL=jev-latest
JEV_SLOW_REASONING_THRESHOLD=0.8
JEV_LOW_CONFIDENCE_THRESHOLD=0.65
JEV_GRAPH_PROJECTION_THRESHOLD=0.8
```

나머지 기준과 state 상한은 `backspace_mvp/jev_thresholds.json`에 있다. `JEV_THRESHOLDS_FILE`로 다른 JSON을 선택할 수 있다. 기본 no 기준 0.2, yes 기준 0.8, Choice 선택 확률 0.8, Choice/Score confidence 0.65, state 18,000자, 이웃 최대 3개다. threshold 파일은 패키지에도 포함한다. 질문과 threshold 내용 해시가 캐시 식별자에 들어간다. 임계값 사이의 Noul은 unknown이고, 낮은 Choice confidence는 선택 확정값으로 쓰지 않는다.

명확한 contradicts/extends는 slow reasoning으로 보낸다. 명확한 충돌은 graph도 만든다. 3개 graph Noul 중 하나라도 높거나 unknown이면 projection을 실행한다. Jev 오류·과대 state·키 없음은 기존 경로로 넘어간다. 실패를 false로 저장하지 않고 다시 시도할 수 있게 한다. 기존 문서를 디자인 변경 등의 이유로 자동 재분석하지 않는다.

`jev-latest`의 실제 모델은 호출 기록에 보존한다. 재현 가능한 비교에서는 `JEV_MODEL`을 특정 버전으로 고정해야 한다. alias가 서버에서 바뀌었다는 이유만으로 이미 저장된 성공 판단을 재호출하지는 않는다.

## 저장·재개

교사 자료와 시험범위 각각의 workspace 아래 `jev_decisions/`에 저장한다.

```text
note_router/             실제 note bundle
graph_gate/              같은 bundle을 참조한 graph 분기
hypothesis_validation/   실제 후속 가설 검증
hypothesis_prefilter/    명시 호출 시 사용할 확장점
teacher_update_gate/     명시 호출 시 사용할 확장점
planning_gate/           명시 호출 시 사용할 확장점
```

`jev_decision.schema.json`에 기록 계약을 정의했다. decision_id/type, state_hash, question_version/versions/hash와 실제 질문, bounded state_snapshot, configured/actual model, raw_answers, probabilities, confidence, threshold_version/원 설정, Python final_route, created_at, related_note_ids/hypothesis_ids, status, attempt_count를 보존한다. 키·헤더·provider 오류 본문은 저장하지 않는다. 성공 캐시는 원답 계약을 다시 검사하며 실패 판단은 성공 캐시로 사용하지 않는다.

노트 본문과 provenance는 불변이다. 거절된 노트와 오래된 source fingerprint를 검색에서 제외한다. 중복은 소스별 노트를 지우거나 빈도를 합치는 뜻이 아니다. `dataset.sources[].graph_projection`에 total_notes/projected_notes/notes_only와 생략한 원문 span·decision ID를 저장한다. 그래프 집계는 projection한 부분의 빈도다. 시험은 자료 graph gate로 누락하지 않는다.

## NVIDIA 실패 정책

`NvidiaProvider.complete`의 자동 token/timeout 증가는 제거했다. timeout과 output_limit은 첫 실패에서 `SemanticReductionRequired(stage, reason)`를 내보낸다. 요청마다 retry_index/elapsed_seconds/입출력 사용량을 기존 로그에 남긴다. transport disconnect·429/5xx·잘못된 JSON/계약에만 최대 한 번 대체 모델을 사용한다. 인증 오류는 재시도하지 않는다.

- Understanding Note: 정확한 원문 offset을 유지한 절반 크기 구간으로 최대 2단계 축소. raw note 체크포인트와 `.reduction.json` 저장.
- 자료 graph: catalog를 현재 원문에 나타난 이름 최대 64개로 제한하되 전체 catalog의 ID 검증은 유지. 실패하면 해당 원문 구간을 최대 2단계 축소. 부모 단계의 미완료 graph 변경은 rollback하고 성공한 체크포인트는 보존.
- 가설: 완전한 근거 카드와 패턴 선택 개수 및 가설 개수·노트 문맥 예산을 줄여 최대 2단계 축소. 서로 다른 지지 문항 2개 요건·정확한 근거 검증을 유지. 선택된 실제 범위를 artifact에 기록.
- A-MEM metadata: timeout/output_limit이면 이미 생성된 제목·주제만 임시 검색 필드로 복사하고 metadata_status=needs_review와 `.deferred.json` 저장. 같은 metadata prompt를 다음 실행에서 반복하지 않음. evolution 실패는 원래 내용 보존·실패 표시.
- 안전한 축소가 없는 문항/그림/계획 단계: 성공으로 위장하거나 인용을 임의로 자르지 않음. 실패와 완료 체크포인트를 유지하며 추가 분할은 후속 작업.

원래 NVIDIA timeout 설정값과 기존 VLM 단계별 제한은 올리지 않았다. 문항 검토·새 해석을 모두 Jev로 대체하지 않았다.

## 검증과 측정

`tests/test_semantic_control.py`는 A–G 및 cache invalidation, unknown, raw 확률, 출처 보존, 축소 재개, metadata 임시 처리, 가설 → 기존 score → Teacher Model → 계획 회귀를 검사한다. 모의 판단은 라우팅 구현 검증이며 모델 정확도 검증이 아니다.

최종 확인: Python 128개 통과(새 16개 포함), `npm run check` 통과, `pip check` 충돌 없음. 기존 시간/출력 상한 확대를 기대하던 테스트는 ‘첫 실패에서 축소 요청을 넘기고 동일 prompt를 재전송하지 않음’이라는 새 정책으로 변경했고 별도 축소·재개 검증을 추가했다.

실제 비교는 `output/jev_control_validation/live_p6/benchmark.json`, 질문 v2의 실제 API 확인은 `latest_questions_probe.json`에 있다. 비교에서 원래 노트 본문·source quote를 보존했고 graph/Teacher Model을 user workspace에 쓰지 않았다. Negative control은 일부러 무관한 가설이며 실제 교사에 대한 주장으로 저장하지 않았다. baseline과 controlled 모두 timeout=0/output_limit=0이었다. 동일 원문 노트를 반복 제출한 **메타데이터·연결 미세 실험**이므로 전체 처리의 속도·정확도 개선율로 확대하지 않는다.

| 지표 | baseline | controlled |
|---|---:|---:|
| NVIDIA 요청 수 | 2 | 0 |
| Jev 요청 수 | 0 | 1 |
| 평균 NVIDIA 입력 토큰 | 869 | 해당 없음 |
| 평균 NVIDIA 지연 | 18.492초 | 해당 없음 |
| 총 NVIDIA 지연 | 36.984초 | 0초 |
| 총 Jev 지연 | 0초 | 0.297초 |
| 실제 timeout / output_limit | 0 / 0 | 0 / 0 |
| 추정 청구 비용 | 미측정 | 미측정 |

실제 corpus의 Teacher output regression은 미측정이다. 모의 전체 체인에서 근거·지원 문항·학생 실제 행동 not_observed·계획 시간 예산을 유지하는 것은 검사했다. 새 질문의 지지/반박 정확도, calibration, 전체 시간 초과 변화는 별도 고정 benchmark가 필요하다.

```powershell
./.venv-ocr/Scripts/python.exe -m unittest discover -s tests
npm run check
# 아래 명령은 실제 API를 사용한다. 새 output 경로를 지정해야 한다.
./.venv-ocr/Scripts/python.exe scripts/validate_jev_control.py --live --note output/amem_validation_p6/memory/notes/un_3dffd64d037bb891f58789cbdd74.json --out output/jev_control_validation/new_comparison
```

## 다음 후보

Teacher Hypothesis 이전 evidence relevance/teacher signal 선별, 기존 가설에 새 근거만 더하는 update gate, 학생 데이터의 local_adjustment/full_replan 분리를 순서대로 붙일 수 있다. 이번에는 `future_questions` / `SemanticControl.future_gate` 계약만 준비했고 기존 planner의 자동 동작은 변경하지 않았다. 새 의미 이해·VLM·가설 작성·학습 행동 생성은 LLM에 남겨야 한다.
