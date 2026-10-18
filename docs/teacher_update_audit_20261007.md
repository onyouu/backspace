# Teacher Model 갱신 보완 계획 — 2026-10-07

## 현재 코드에서 확인한 흐름

자료 읽기 → 원문 연결 이해 노트 → 자료/문항 그래프 → 반복 패턴 → 변경된 증거별 기존 가설 관계 판단 → 새 패턴에만 사전 선별/novelty → 필요한 경우 NVIDIA 후보 1개 → Jev 통합 → Python 모델 저장.

TeacherModelUpdateEngine, 관계 5문항 묶음, 독립 가설 상태, 델타, 피드백, 실패 재개는 이미 있다. 전체 Teacher Model JSON을 NVIDIA가 재작성하는 경로는 기본 경로에 없다. 수동 재생성만 기존 묶음 가설 생성 경로를 사용한다.

| 조사 대상 | 현재 함수/계약 |
|---|---|
| 가설 생성 | `hypotheses.build_teacher_hypotheses`: 수동 경로. 자동 경로는 `teacher_incremental.update_teacher_model` 안의 후보 1개 생성 callback |
| 전체 모델 조립 | `teacher_model.build_teacher_model`: Python 조립 |
| 모델 저장 | `schemas/teacher_model.schema.json`, `teacher_hypotheses.schema.json`, 증분 `teacher_model/state.json` |
| 반복 패턴 | `patterns.build_patterns`: node/edge/path/subgraph, 독립 문항 지지 수/분모 |
| Jev 요청 | `jev.JevProvider.decide`, `semantic_control.SemanticControl.judge`: typed 응답 검증/캐시 |
| 기존 점수 | `scoring.build_teacher_scores`: 개념 6차원 점수와 원점수 보존 |
| A-MEM | `understanding.teacher_memory_context`, `teacher_incremental.retrieve_memory`: 원문 연결 노트 조회/장애 fallback |
| 원문 근거 | evidence.citations의 source/source_sha256/locator/raw_evidence/char_start/char_end |
| 계획 연결 | `study_plan._teacher_context`: active 가설만, 범위 확인 대기 제외 |
| NVIDIA 위치 | 이해 노트·메모리 의미 보강·자료/문항 의미 분석·새 교사 후보·선택적 자연어 계획 |
| 재생성 | CLI `--manual-rebuild`. 기본 갱신은 변경 증거만 처리. 버전/정책/범위 불일치는 명시적 조치 요구 |
| 재개 | stage_state 단계 저장 + teacher_update 원자적 체크포인트/관계·후보 캐시/부분 기록 복구 |

## 확인된 빈틈과 최소 변경

1. 기존 가설을 갱신하는 그래프 증거/이해 노트 경로가 teacher-prefilter를 거치지 않는다. 공통 증거별 선별을 추가하고, 같은 증거에 대한 관련 가설 여러 개를 하나의 선별 요청에 제공한다.
2. 일반 교과 설명은 증거를 보존하면서 관계 호출을 생략한다. 실제 문항과 이미 확인된 반례는 일반 설명 판정만으로 제외하지 않는다. 선별 실패/모호함은 pending_review로 남기며 unrelated로 바꾸지 않는다.
3. 일반 설명 선별 결과도 원자적 상태와 별도 기록에 저장한다. 재실행에서 예산을 계속 차지하거나 다시 API를 호출하지 않도록 한다. 증거/가설 문구·범위/모델/질문 버전 변경은 새 선별 대상이다.
4. 이해 노트 갱신에 해당 노트 원문을 바탕으로 기존 메모리 조회를 연결한다. 조회 실패 시 검증된 노트를 이용하는 기존 fallback을 유지한다.
5. 이전 원문 버전의 관계가 승격 제한을 잘못 유지하지 않도록 현재 증거 해시와 대조한다. 서버 코드 변경 감지에 교사 갱신 모듈을 포함한다.

기존 질문 문구·버전·스키마·수동 재생성·원본 파일은 유지한다. 기존 체크포인트에는 선별 기록 필드만 추가하며 삭제/자동 재평가하지 않는다.

## 검증 범위

기존 A–I 테스트를 유지하고 일반 설명 생략/재실행/실패/반례 보호/문항 보호/가설 변경/원문 버전 교체를 확인한다. 현재 실제 저장된 Teacher Model의 가설은 0개다. 따라서 실제 기존 가설 3–5개 비교는 수행했다고 주장할 수 없으며 별도 잠정 문장 실험과 구분한다.
