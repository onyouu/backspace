# 구현 단계 v0.5 — Jev Scoring Layer

2026-10-06 업데이트: v0.7 제작 후 합성 샘플 통합 검증을 완료했습니다. [검증 범위와 남은 평가](implementation_status.md), [생성 결과](../output/integration_v07_preview.md)를 참고하세요. 아래 제작 당시의 미검증 표기는 당시 상태입니다.

제작 상태: TypeSafe HTTP 어댑터·차원별 점수화·Python 요약·CLI·JSON 스키마 작성. **실행·테스트·인증된 API 호출은 하지 않았다.** v0.7 제작 후 통합 검증한다. 공식 문서의 요청/응답 형식을 참고했으며 실제 서버 응답과의 호환성은 아직 검증하지 않았다.

## API 계약

[공식 Quick start](https://docs.typesafe.ai/introduction/quickstart)와 [Score 문서](https://docs.typesafe.ai/primitives/score)를 기준으로 `POST https://api.typesafe.ai/v1/systemone`에 `model`, 문자열 `state`, 독립 `questions`를 보낸다. 각 질문은 `type: score`, 지시문, 서술형 level 배열이다. 모델은 `.env`의 `JEV_MODEL`(기본 `jev-latest`), 키는 `TYPESAFE_API_KEY`로 읽는다. 키·인증 헤더·서비스 오류 본문을 로그에 저장하지 않는다. 원본 jev 파일과 로컬 `.env`는 변경하지 않는다.

실제 실행 시 선택한 원문·자료 관찰·문항 요구·가설·반복 통계를 TypeSafe로 전송한다. 직접 HTTP를 사용하므로 별도 TypeSafe SDK 설치는 필요 없다. 이번 단계는 NVIDIA 생성 호출을 추가하지 않는다.

Score는 level 위치의 점수이며 0~1 진실 확률이 아니다. 현재 기준표는 각 차원에 4개 서술형 level(0~3)을 두었다. 원 score, `legend`, 각 level의 `probabilities`, `confidence`를 그대로 보존하고 비교용 값만 score/3으로 정규화한다. confidence는 서버가 반환한 값을 보존하며 인간 검수 통과나 과학 정확도를 뜻하지 않는다.

## 가설과 개별 근거

가설마다 다음을 독립 질문으로 평가하도록 구현했다.

- `support`: 제공 원문이 조건부 가설을 지지하는 정도.
- `counter`: 제공 원문이 가설을 반박하는 정도. 낮은 값은 전체 자료에 반례가 없다는 뜻이 아니다.
- `evidence_quality`: 원문 대응·조건 명시·근거 독립성.
- `consistency`: 선택적으로 제공한 동일 교사의 기존 v0.6 Teacher Model과 관련 조건의 일관성. 기존 모델이 없으면 null/`not_observed`.

각 선택 근거에도 support/counter/evidence_quality를 따로 저장한다. 생성 LLM의 지지/반박 사유를 사실로 취급하지 않고 원문을 우선하도록 요청한다. Jev에 새 가설 문장이나 설명을 생성하도록 요구하지 않는다. 판단의 출처는 원자료·입력 snapshot과 기준표로 추적하며 자유 서술형 판단 이유를 꾸며 저장하지 않는다.

가설 원본의 `confidence: null`, `pending_jev`를 직접 수정하지 않는다. `teacher_scores.json`이 별도의 판단 자산이며 v0.6에서 원 가설과 연결한다. Jev 판단을 받아도 가설 상태는 검증된 교사 성향으로 승격하지 않는다.

## 개념의 여섯 차원

| 차원 | 입력 |
|---|---|
| Recurrence | 자료 source/page 빈도, 시험 support/분모 |
| Source Diversity | 독립 원자료 ID·종류·시험 분포 |
| Exam Relevance | 포함 시험의 개념 적용·요구 산출물 |
| Reasoning Centrality | 연결된 요구 사고·이해 증거와 적용 연결 |
| Explicit Emphasis | 개념과 연결된 명시적 강조 원문 |
| Evidence Quality | 원문 인용·조건·기존 추출 검토 상태 |

빈도가 teacher importance로 자동 변환되는 구조가 아니다. Python은 원 통계를 계산하고 Jev가 각 차원을 판단한다. 문항에서 반복된 횟수와 자료의 서로 다른 source/page 빈도를 합쳐 하나의 등장 횟수로 만들지 않는다.

관찰 없는 차원은 null/`not_observed`다. 명시적 강조가 관찰되지 않으면 강조 중요도 0을 채우지 않는다. 포함 시험 자체가 없으면 Exam Relevance는 미관찰이다. 포함 시험은 있지만 해당 개념이 연결되지 않은 경우에는 그 범위의 비출현을 판단 입력으로 쓴다.

Python 요약 `Teacher Salience`는 다음 초기 가중치를 사용한다: recurrence .20, diversity .15, exam relevance .25, reasoning centrality .15, emphasis .10, evidence quality .15. 실제 점수화한 차원들의 가중 합을 사용 가중치 합으로 나눈다. 최소 사용 가중치 .65와 recurrence/exam relevance/evidence quality 관찰이 필요하며 부족하면 요약도 null이다. 가중치·사용 가중치·`weight_version`을 보존한다. 이는 미보정된 잠정 요약이며 중요도 확률이 아니다. 원 차원 값과 낮은 confidence 표시는 버리지 않는다.

## 범위·캐시·저장

기본 상한: 개념 24개, 가설 8개, 가설별 원 근거 24개, 요청당 질문 32개, 요청 문맥 64000자. 개념은 포함 시험 support와 ID로 선택하고 가설은 저장 순서로 선택한다. 제외한 대상과 근거 ID도 남긴다. 개념 문맥은 선택 개념에 연결된 포함 문항·자료를 사용하고 상한을 넘으면 원문을 자르지 않고 오류를 낸다.

같은 판단 state의 여러 질문을 한 요청에 묶는다. 근거 ID별 질문도 그 state에서 독립 차원으로 평가하도록 만든다. 개념/가설별 state가 다르므로 각각 요청하며, 배치 상한이 작으면 여러 요청으로 나뉜다. 동시 요청·자동 반복 재시도는 추가하지 않았다.

`jev_checkpoints/`는 입력 문맥·기준표·모델 설정 해시가 같은 완료 응답을 재사용하도록 구현했다. 응답의 질문 ID·type·legend·점수 범위·분포 level·확률 합을 검사한다. 변경된 입력은 이전 checkpoint를 사용하지 않는다. `jev-latest`의 실제 반환 모델 이름도 보존하며 별칭의 서버 버전 변경을 자동 감지하지는 않는다. 새 서버 판단이 필요하면 `--refresh`를 쓴다.

최종 파일은 dataset 옆 `teacher_scores.json`, 이전 버전은 `teacher_score_history/`다. 전체 대상이 완료돼야 최종 상태를 교체하며 중간 실패 시 기존 최종 파일을 유지하고 완료 checkpoint만 남긴다. 기록에 원 점수·분포·confidence·기준표·실제 모델·입력 해시·정규화 값·source 근거·선택 범위를 보존한다. API 사용량은 기존 `usage_log.json`에 TypeSafe run으로 추가하고 모르는 비용은 null로 둔다. 파일별 atomic replacement이며 동시 쓰기는 지원하지 않는다.

## 실행 방법 — v0.7 이후 검증 시 사용

```powershell
python -m backspace_mvp score_teacher --state state/teacher_arch_v02/dataset.json
# 호출 규모를 줄여 첫 통합 검증에 사용
python -m backspace_mvp score_teacher --state state/teacher_arch_v02/dataset.json --max-concepts 4 --max-hypotheses 2 --max-evidence 4
```

앞선 `mine_patterns`, `build_teacher_hypotheses` 결과가 필요하다. 이전 Teacher Model과 비교할 때만 `--teacher-model`로 동일 교사의 v0.6 파일을 제공한다. 현재 v0.6 제작 전에는 이 옵션을 사용하지 않는다. `JEV_TIMEOUT_SECONDS` 기본값은 45초다.

코드: [jev.py](../backspace_mvp/jev.py), [scoring.py](../backspace_mvp/scoring.py). 저장 계약: [teacher_scores.schema.json](../backspace_mvp/schemas/teacher_scores.schema.json).

다음은 v0.6 Teacher Model 제작이다. 원 통계·가설·Jev 차원 값과 잠정 요약을 연결하고 버전별 근거·반례를 유지한다.
