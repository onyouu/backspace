# 구현 단계 v0.6 — Teacher Model

2026-10-06 업데이트: v0.7 제작 후 합성 샘플 통합 검증을 완료했습니다. [검증 범위와 남은 평가](implementation_status.md), [생성 결과](../output/integration_v07_preview.md)를 참고하세요. 아래 제작 당시의 미검증 표기는 당시 상태입니다.

제작 상태: Python 모델 조립·입력 연결·검토 표시·버전 저장·CLI·JSON 스키마 작성. **실행·테스트·API 호출은 하지 않았다.** v0.7 제작 후 통합 검증한다. 아래 사용법과 동작은 구현 계약이며 확인된 실행 결과가 아니다.

## 핵심 자산

`material_graph.json`, 활성 Question Graph, `patterns.json`, `teacher_hypotheses.json`, `teacher_scores.json`을 하나의 `teacher_model.json`으로 조립한다. 추가 LLM/Jev 요청 없이 Python으로 연결한다. 다른 교사의 상태, 오래된 snapshot, 중복 ID, 점수 대상 범위 불일치, 원 점수/정규화/가중 요약 불일치를 실행 시 거부하도록 구현했다.

| 모델 항목 | 내용 |
|---|---|
| `concept_importance` | 공통 Concept ID·라벨·alias, 잠정 중요도, 원 Jev 차원/분포/confidence/rubric, 자료 관찰, 근거 문항 |
| `dominant_reasoning` | 반복된 사고 코드의 node/edge/path/subgraph, 문항 support·분모·시험별 분포·실제 match·원문 근거 |
| `assessment_ideals` | 원 조건부 가설·범위·지지/반례·대안·추가 자료·한계, 가설/근거별 Jev 판단, 검토 우선 표시 |
| `evidence_registry` | 가설 근거의 원자료 구절·위치·SHA·추출 confidence와 원 항목 ID |
| `material_relations` / `material_sources` | 자료 관계의 조건·assertion·기존 검토·원문 근거와 출처 metadata |
| `inputs` / `coverage` | dataset·단계별 자산 해시, 기존 모델 일관성 참조 해시, 실제 포함/제외/선택 범위 |

모델은 `provisional_evidence_model`이며 학생 행동은 `not_observed`다. 관찰된 요구 사고·후보 해석·Jev 판단을 구별한다. 반복 사고는 검증된 교사 선호가 아니며 시험 필터와 입력 범위 안의 구조 통계다.

모든 등록 개념과 생성 가설을 유지한다. v0.5의 대상 상한 때문에 점수가 없는 개념은 `teacher_importance: null`, `not_scored`; 가설은 `pending_jev`다. 관찰이 부족해 계산하지 못한 중요도도 null이다. 이전 모델의 점수를 새 관찰에 자동 이월하지 않는다. 점수 있는 항목의 중요도는 v0.5의 가중 요약을 그대로 연결하며 원 차원·분포·confidence를 버리지 않는다.

## 평가관 가설과 검토 표시

`assessment_ideals`는 확정 평가관이 아니다. 원 가설의 적용 조건, 반례 검색 범위, 대안 설명과 미검토 상태를 유지한다. score가 있어도 가설의 confidence를 확률로 채우지 않는다.

Python 검토 정책 `review-priority-1`을 별도로 저장한다.

- 점수 없음: `pending_scoring`.
- 필요 차원 미관찰: `insufficient_observation`.
- 정규화 반박 점수 ≥ .5: `counter_evidence_review`.
- support/counter/evidence_quality 중 confidence < .5: `uncertain_judgement_review`.
- 정규화 지지 또는 근거 강도 < 2/3: `weak_support_review`.
- 그 외: `provisional_support`.

이는 초기 검토 분류 기준이며 학습된 임계값, 가설 참/거짓 판정, 교사 성격·사적 의도 추론이 아니다. 미보정 점수가 높아도 독립 검증을 대신하지 않는다.

## 갱신과 이전 모델 비교

같은 입력으로 조립하면 내용 해시와 revision을 유지하도록 구현했다. 새 자료·시험·가설·판단·범위가 바뀌면 현재 snapshot을 갱신하고 전체 이전 모델을 `teacher_model_history/`에 보존한다. 현재 목록에 없는 과거 가설/문항은 이력으로 남기고 현재 모델의 support에 합치지 않는다. 이전 점수와 신규 점수를 반복 더하는 방식이 아니다.

`revision`, `previous_hash`, `updated_at`, 단계별 입력 해시로 갱신 근거를 추적한다. 같은 출력 경로에 다른 교사 모델이나 이전 실험 보고서가 있으면 자동 변환·덮어쓰지 않는다. 파일별 atomic replacement이며 동시 쓰기는 지원하지 않는다.

v0.5 `score_teacher --teacher-model ...`도 새 스키마를 검사하도록 연결했다. 기존 모델 전체 근거 저장소 대신 가설의 concept/reasoning 범위와 연결된 평가관 후보 최대 8개, 개념 중요도 최대 12개의 요약을 판단 문맥으로 제공한다. 제공/전체 관련 항목 수와 이전 모델 해시를 남긴다. 관련 항목이 없으면 consistency를 null로 유지한다. 이전 모델과 일관돼도 사실로 검증된다는 뜻은 아니다.

## 실행 방법 — v0.7 이후 검증 시 사용

앞선 자료·문항·패턴·가설·점수 파일이 필요하다.

```powershell
python -m backspace_mvp build_teacher_model --state state/teacher_arch_v02/dataset.json
```

기본 출력은 dataset 옆 `teacher_model.json`이다. 사용자 지정 입력:

```powershell
python -m backspace_mvp build_teacher_model --state state/teacher_arch_v02/dataset.json --scores state/teacher_arch_v02/teacher_scores.json --out state/teacher_arch_v02/teacher_model.json
```

이전 실험용 `build_teacher_model` 명령은 `build_legacy_teacher_report`로 보존했고 기본 파일명을 `legacy_teacher_report.json`으로 구별했다. Python의 기존 `pipeline.build` 인터페이스는 유지하며 v0.6 모델을 실험 보고서로 덮어쓰지 못하도록 보호했다. 기존 실험 Planner는 새 모델 계약을 처리하지 않으며 v0.7에서 연결한다.

코드: [teacher_model.py](../backspace_mvp/teacher_model.py). 저장 계약: [teacher_model.schema.json](../backspace_mvp/schemas/teacher_model.schema.json).

다음 제작은 v0.7 새 시험범위 자료 + Teacher Model → 공부계획이다. 학생 정보 없이 교사 상대 중요도를 시작점으로 삼고, 계획의 상태·변경 근거·이력을 지속 저장한다.
