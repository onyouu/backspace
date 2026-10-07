# 구현 단계 v0.3 — 반복 Pattern Engine

2026-10-06 업데이트: v0.7 제작 후 합성 샘플 통합 검증을 완료했습니다. [검증 범위와 남은 평가](implementation_status.md), [생성 결과](../output/integration_v07_preview.md)를 참고하세요. 아래 제작 당시의 미검증 표기는 당시 상태입니다.

제작 상태: Python 코드·CLI·JSON 스키마 작성. 사용자 요청에 따라 **이번 단계에서 실행, 테스트, 실제 API 호출을 하지 않았다.** v0.7 제작 후 통합 검증한다. 이전 v0.2의 테스트 결과를 이 단계의 검증 결과로 사용하지 않는다.

## 입력과 집계 범위

`dataset.json`과 `question_graphs/index.json`의 활성 문항 파일을 읽는다. `history/` 파일이나 여러 문항을 합친 그래프는 분석 입력으로 사용하지 않는다. dataset과 index/문항의 ID·해시·revision·교사 범위를 대조하는 입력 검증을 코드에 포함했다. 누락되거나 오래된 내보내기는 실행 시 오류를 내며 `export_question_graphs`로 먼저 갱신해야 한다.

`grounded-2.3` 문항만 포함한다. 이전 계약의 문항은 `coverage.excluded_questions`에 재분석 필요로 남긴다. `--exam-id`는 시험 범위와 분모를 함께 제한한다. 해당 시험에 이전 문항만 있다면 포함 문항 0개, 빈 패턴과 제외 목록을 저장한다. 존재하지 않는 시험 ID는 오류다.

두 종류의 패턴을 별도로 집계한다.

| mode | 노드의 동일성 | 용도 |
|---|---|---|
| reasoning_structure | 사고 code | 과학 내용이 달라도 같은 요구 사고 구조가 반복되는지 확인 |
| concept_reasoning | 공통 Concept ID + 사고 code | 특정 개념에 결합된 요구 사고 구조 확인 |

Task/이해 증거/출제 의도 후보의 자유 문장은 같은 의미라고 자동 병합하지 않는다. 이 단계의 두 mode에는 Concept과 Reasoning 사이 연결 및 Reasoning 사이 연결만 사용한다. Concept 라벨과 과학 내용·조건·기준은 원문 graph의 match ID로 역추적한다. 코드가 같은 두 단계도 같은 구체적인 과학 내용이라고 단정하지 않는다.

## 네 가지 패턴

- `nodes`: 개념 또는 사고 코드의 출현. 같은 문항의 같은 코드가 여러 번 나와도 support는 1이다.
- `edges`: 시작 노드의 signature, 관계, 끝 노드의 signature. 방향과 관계 이름을 유지한다.
- `paths`: 문항 내부의 방향성 단순 경로. 2~3개 edge를 집계하고 동일 노드를 다시 방문하지 않는다. 다른 문항을 이어 경로를 만들지 않는다.
- `subgraphs`: 3~4개 노드의 약연결된 유도 부분 그래프. 선택된 노드 사이의 모든 방향·관계·병렬 edge를 포함하고 정확한 동형 비교로 정규화한다. 분기와 합류를 그대로 남긴다.

`reasoning_structure`와 `concept_reasoning` 양쪽에 같은 사고 패턴이 나올 수 있으므로 두 mode의 support를 합치면 안 된다. 유도 부분 그래프는 추가 연결이 있는 더 큰 구조와 동일한 motif로 취급하지 않는다.

각 패턴에 다음을 저장한다.

| 필드 | 의미 |
|---|---|
| `pattern_id` | engine 버전·mode·종류·정규화 descriptor의 결정적 해시 |
| `support` | 해당 패턴이 존재하는 서로 다른 포함 문항 수 |
| `denominator` / `support_ratio` | 전체 포함 문항 수 / support ÷ denominator |
| `occurrence_count` | 문항 안에서 발견한 실제 노드·연결·경로·부분 그래프 출현 수 |
| `is_repeated` | 서로 다른 문항 2개 이상에서 출현 |
| `meets_min_support` | 사용자가 지정한 최소 support 충족 |
| `by_exam` | 시험별 support·분모·비율. 지지 문항 0개인 포함 시험도 표시 |
| `question_ids` / `evidence` | 근거 문항, graph 해시, 실제 match 노드/edge ID, 원문 인용·위치·confidence |

singleton도 보존한다. `--min-support 1`을 지정해도 한 문항만의 출현은 `is_repeated: false`다. 빈도 비율은 해석 확신도나 Teacher Importance가 아니다. 출제 의도·교사 가설·Jev 점수는 생성하지 않고 학생 행동은 `not_observed`다.

match의 `node_ids`는 descriptor의 노드 순서다. path의 `edge_ids`는 경로 순서이며, subgraph의 edge 배열은 실제 원문 edge ID 목록이다. 상세 관계는 원래 question graph에서 확인한다. 인용의 confidence는 기존 추출 값 그대로이며 새로운 신뢰 점수를 만들지 않는다.

## 실행 방법 — v0.7 이후 검증 시 사용

아래 명령은 사용법이며 이번 단계에서 실행하지 않았다. v0.2가 만든 로컬 합성 예시를 그대로 입력으로 쓸 수 있다. 새 분석이나 NVIDIA 호출이 필요하지 않다.

```powershell
python -m backspace_mvp mine_patterns --state state/teacher_arch_v02/dataset.json
python -m backspace_mvp mine_patterns --state state/teacher_arch_v02_offline/dataset.json --out state/teacher_arch_v02_offline/patterns.json
```

기본 출력은 지정 dataset 옆 `patterns.json`이다. 시험 범위와 탐색 상한을 지정할 수 있다.

```powershell
python -m backspace_mvp mine_patterns --state state/teacher_arch_v02/dataset.json --exam-id architecture_v02_demo --min-support 2 --max-path-edges 3 --max-motif-nodes 4
```

문항별·mode별 작업 상한은 기본 50000이다. 노드/edge/path match와 subgraph 후보 및 match를 작업량으로 센다. 상한을 넘으면 부분 통계를 저장하지 않고 기존 결과를 유지하도록 구현했다. 필요하면 `--max-candidates`를 조정한다. 상한을 올리면 실행 시간과 출력 크기가 증가한다.

이전 결과와 집계 내용이 같으면 revision과 파일을 유지하도록 구현했다. 입력·범위·설정·결과가 달라지면 이전 결과를 `pattern_history/`에 저장한 뒤 revision을 늘린다. 결과의 `dataset_hash`, 활성 index 해시, 각 입력 graph 해시·revision으로 분석 snapshot을 구분한다. 파일은 atomic replacement이고 동시 쓰기는 지원하지 않는다.

## 저장 계약과 다음 단계

코드: [patterns.py](../backspace_mvp/patterns.py). 계약: [patterns.schema.json](../backspace_mvp/schemas/patterns.schema.json). `mine_patterns`는 기존 실험용 `build_teacher_model`을 바꾸지 않는 별도 단계다.

v0.4는 `patterns.json`의 관찰 통계·실제 match·자료 네트워크를 입력으로 가설을 생성한다. 지지 범위·반례·대안·검증할 추가 자료를 따로 저장해야 하며, 빈도만으로 평가관을 확정하지 않는다.

미검증 사항은 [구현 상태와 최종 검증 계획](implementation_status.md)에 모아 둔다.
