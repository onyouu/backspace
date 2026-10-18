# 구현 단계 v0.7 — Teacher Model + 새 자료 → 지속 공부계획

2026-10-06 업데이트: v0.7 제작 후 합성 샘플 통합 검증을 완료했습니다. [검증 범위와 남은 평가](implementation_status.md), [생성 결과](../output/integration_v07_preview.md)를 참고하세요. 아래 제작 당시의 미검증 표기는 당시 상태입니다.

제작 상태: 상대 중요도 판단·활동 생성·시간 배정·진행/메모 저장·CLI·JSON 스키마 작성. **이번 단계에서도 실행·테스트·API 호출은 하지 않았다.** v0.1~v0.7 제작 후 통합 검증을 다음 작업으로 수행한다. 아래 명령과 저장 동작은 구현 계약이며 실제 실행 결과가 아니다.

## 입력과 역할

기존 교사의 v0.6 `teacher_model.json`과 새 시험범위의 별도 자료 dataset/`material_graph.json`을 읽는다. 원 Teacher Model을 바꾸거나 새 범위를 과거 시험 통계에 섞지 않는다. 교사 scope와 각 입력의 스키마·해시·자료 관찰 대응을 검사하도록 구현했다.

- Jev: 새 개념의 teacher-relative importance, 연결 근거 강도, 추가 메모가 있을 때 계획 수정 필요성을 독립 Score로 판단.
- NVIDIA: 개념별 학습 활동·산출물·완료 기준·조건을 한국어로 생성.
- Python: 참조/ID·학습 깊이·과제 시간·일정·진행 상태·입력 snapshot·이력 관리.

초기 Study Priority는 교사 상대 중요도를 사용한다. Student Weakness·Forgetting·Performance는 미관찰로 유지한다. 완료 버튼/메모만으로 정답률·이해·약점을 추론하지 않는다.

## 새 개념과 교사 근거 연결

정확한 공통 ID 또는 라벨/alias 일치로 동일 개념 후보를 연결한다. 여러 교사 개념과 동시에 일치하면 자동 선택하지 않고 입력 정리를 요구한다. 자료의 관련 관계와 연결 개념도 문맥에 포함한다. 직접 연결이 없으면 상위 중요도 개념을 비교 앵커로 제공하되 동일 개념이라고 병합하지 않는다.

새 개념에 제공하는 교사 문맥은 비교 개념 최대 8개와 관련 평가관 가설 최대 6개다. 관련 가설이 없으면 초기 후보 4개를 조건부 비교 대상으로 제공한다. 모든 가설·중요도는 잠정 모델의 판단이며 검증된 교사 선호가 아니다.

Jev는 상대 중요도와 근거 강도를 각각 4개 서술형 level로 판단한다. 원 score·legend·분포·confidence·rubric·실제 모델·요청/문맥 해시를 저장한다. 중요도는 score/3이며 진실 확률이 아니다. 교사 모델에 점수 있는 근거 자체가 없으면 중요도를 만들어 채우지 않는다. 낮은 confidence·약한 연결·미관찰은 검수 필요로 남긴다.

처리할 개념의 기본 상한은 12개다. 동일 개념에서 이전 중요도가 확인되는 개념을 우선 선택하고 이후 Jev 판단으로 선택 범위 안의 순서를 정한다. 제외한 개념 ID를 기록하므로 전체 새 자료의 최적 순위라는 주장은 하지 않는다.

## 학습 깊이·활동·시간

| 상대 중요도 | 깊이 | 초기 시간 정책 |
|---|---|---|
| ≥ .75 | 깊게 이해 + 적용 | 이해/적용 각 45분 |
| ≥ .5 | 이해 + 적용 | 각 30분 |
| ≥ .25 | 기본 이해 | 25분 |
| < .25 | 빠른 확인 | 10분 |
| null | 근거 확인을 포함한 기본 이해 | 25분 |

이는 초기 설계 정책이며 학생 속도·효과를 측정한 결과가 아니다. 미관찰을 낮은 중요도 0으로 취급하지 않는다.

Python blueprint의 과제 ID·종류·예상 시간을 NVIDIA가 임의 변경하지 못하도록 한다. 모델은 각 과제의 활동·목표·제출물·완료 기준·조건을 작성한다. 원문 없는 해설을 정답처럼 제시하거나 신규 연습을 실제 기출이라고 쓰지 않도록 지시한다. 문장과 과학 해석은 사람이 검수해야 한다.

기본 예산은 7일 × 하루 60분이다. 높은 우선순위부터 이해→적용 활동을 배치하고 필요하면 한 과제를 여러 날의 session으로 나눈다. 일일 예산을 넘기지 않으며 남는 과제 분량은 `unscheduled_minutes`/`overflow_minutes`로 남긴다. `in_progress`는 수행한 분량을 측정하지 않았으므로 예상 시간 전체를 남은 시간으로 취급한다. `completed`는 새 일정에서 제외한다. 개념 선수학습의 전수 의존 순서를 해결하는 최적화 기능은 아니다.

## 지속 상태와 수정

기본 저장은 Teacher Model 옆 `current_plan.json`이다. `priorities`, `tasks`, `schedule`, `budget`, 입력 해시, generation 기록, 실제 선택/제외 범위와 `events`를 함께 유지한다.

`update_plan`은 API 없이 다음 이벤트를 저장한다.

- `progress`: 지정 과제의 pending/in_progress/completed 변경과 일정 재배치.
- `conversation`: 대화 메모.
- `additional_data`: 추가 데이터 메모. 파일 자체를 자동 읽거나 정답률로 해석하지 않는다.
- `constraint`: 제약 메모.

메모 이벤트는 `needs_revision: true`로 표시한다. 다음 `generate_plan`이 아직 처리하지 않은 메모를 문맥에 넣고, 온라인 모드에서는 Jev의 수정 필요성 판단도 기록한다. 이 점수는 조언이며 변경된 명시 입력/메모로 계획을 생성하는 동작을 자동 차단하지 않는다. 실제 일정 예산은 `--days`/`--daily-minutes`로 지정한 값을 사용하며 자유 메모의 숫자를 자동 파싱하지 않는다. 처리한 메모 ID를 남기고 원문 메모를 삭제하지 않는다. 별도 상주 감시·자동 예약은 추가하지 않았다.

과제 ID와 내용/근거 해시가 같을 때만 완료 상태를 유지한다. 활동·산출물·기준·조건·자료/교사 근거가 바뀌면 pending으로 돌아간다. 시간 배정·우선순위만 바뀌고 과제 내용이 같으면 진행 상태를 유지할 수 있다. 제거된 과제는 이전 전체 계획 이력에서 복구할 수 있다.

같은 입력·설정·미처리 메모 없음이면 현재 계획을 유지한다. 변경 시 이전 전체 계획은 `plan_history/`에 저장한다. Jev와 NVIDIA의 완료 응답은 `plan_checkpoints/`에서 요청 해시로 재사용한다. 모델 설정을 바꿔 새 판단을 원하면 `--refresh`를 사용한다. 실패 시 기존 최종 계획을 유지한다. 파일별 atomic replacement이며 동시 쓰기는 지원하지 않는다.

## API 없는 계획 모드

`--offline`은 두 서비스 호출을 모두 끈다. 정확히 연결된 이전 개념 중요도를 잠정 전이하고 Python 템플릿으로 활동을 만든다. 신규 개념의 중요도를 임의 추정하거나 Jev/NVIDIA 결과로 표시하지 않는다. 중요도가 없으면 기본 이해+근거 확인 활동을 만든다. 이 모드는 비용 없이 저장 구조를 확인할 때 사용하며 온라인 판단과 동일한 품질이라고 가정하지 않는다.

## 실행 방법 — 다음 통합 검증에서 사용

```powershell
# 새 범위 자료는 별도 상태로 분석
python -m backspace_mvp ingest_materials --input data/live_material.txt --state state/new_exam_scope/dataset.json
python -m backspace_mvp generate_plan --model state/teacher_arch_v02/teacher_model.json --materials-state state/new_exam_scope/dataset.json --offline
# 온라인: 선택한 새 개념의 Jev 판단 + NVIDIA 활동 생성
python -m backspace_mvp generate_plan --model state/teacher_arch_v02/teacher_model.json --materials-state state/new_exam_scope/dataset.json --days 7 --daily-minutes 60 --max-concepts 4
```

메모/진행 상태:

```powershell
python -m backspace_mvp update_plan --plan state/teacher_arch_v02/current_plan.json --event-type constraint --note "하루 공부 가능 시간이 30분으로 줄었음"
python -m backspace_mvp generate_plan --model state/teacher_arch_v02/teacher_model.json --materials-state state/new_exam_scope/dataset.json --daily-minutes 30 --offline
# TASK_ID는 current_plan.json에 저장된 실제 과제 ID 사용
python -m backspace_mvp update_plan --plan state/teacher_arch_v02/current_plan.json --event-type progress --task-id TASK_ID --status completed
```

기존 실험용 Planner는 `generate_legacy_plan`으로 보존했다. 새 Teacher Model은 새 `generate_plan`을 사용한다. 원본/새 계약 파일을 이전 실험 기능으로 덮어쓰지 못하도록 보호했다.

코드: [study_plan.py](../backspace_mvp/study_plan.py). 저장 계약: [current_plan.schema.json](../backspace_mvp/schemas/current_plan.schema.json).

v0.1~v0.7 제작 순서는 여기까지다. 이제 [최종 검증 목록](implementation_status.md)에 따라 구조·실패 처리·통합 흐름을 확인하고 제한된 실제 호출 및 실제 교사 자료의 정확도를 평가한다.
