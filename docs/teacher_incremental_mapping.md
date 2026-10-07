# 교사 모델 갱신 전 코드 조사

2026-10-07. 아래 조사를 먼저 작성한 뒤 구현한다. 기존 자료와 기능은 유지한다.

## 실제 현재 흐름

`web.WebStore._work(action=teacher)` → 자료 읽기·ingest → `export_material_graph` / `export_question_graphs` → `patterns.build_patterns` → `hypotheses.build_teacher_hypotheses` (NVIDIA) → `scoring.build_teacher_scores` (Jev) → `teacher_model.build_teacher_model` (Python) → `study_plan.generate_study_plan`.

**Teacher Model 전체를 NVIDIA가 직접 작성하는 함수는 없다.** 느린 가설 생성은 모델 저장 전 단계에 있다. 입력 해시가 바뀌면 가설 문맥을 다시 구성하며, 동일 문맥은 체크포인트를 재사용한다.

| 조사 항목 | 현재 위치와 동작 |
|---|---|
| 가설 생성 | `hypotheses.py:build_teacher_hypotheses`, `prepare_context`, `assemble_candidates`. 최대 8개의 조건부 가설, 정확한 근거 참조, 문항 2개 이상 검증 |
| 모델 생성 | `teacher_model.py:build_teacher_model`. 점수·자료·패턴 해시 검증 뒤 Python으로 조립 |
| 모델 스키마 | `schemas/teacher_model.schema.json`, `teacher_hypotheses.schema.json`, `teacher_scores.schema.json` |
| 반복 구조 | `patterns.py:build_patterns`, `load_active_graphs`. node/edge/path/subgraph, 독립 문항 support/분모·시험별 통계 |
| Jev 클라이언트 | `jev.py:JevProvider.decide/score`, `semantic_control.py:SemanticControl.judge`. 타입 검증, 원 확률·별도 confidence, 요청 캐시 |
| 기존 점수 | `scoring.py:build_teacher_scores`. 가설 지지/반례/근거 품질, 개념 6차원, Python 가중 요약 |
| A-MEM | `amem_adapter.py`, `understanding.py:teacher_memory_context`. 노트 본문·출처·검색; 거절/오래된 자료 제외 |
| 근거 출처 | 원자료 citation의 source/source_sha256/locator/raw_evidence/char_start/char_end/question_id. 가설 evidence_registry가 문항·자료 근거와 연결 |
| 계획 연결 | `study_plan.py:_teacher_context`, `generate_study_plan`. 모델 해시·범위·개념 중요도·가설을 별도 시험범위 자료에 적용 |
| NVIDIA 호출 | perception 이후 understanding 생성, A-MEM metadata/evolution, material/question 의미 구조, 교사 가설, 선택적 자연어 계획. 이번 변경의 주 대상은 교사 가설 단계 |
| 재생성 조건 | 가설 input_context_hash/입력 snapshot/provider 설정/question version 변경. 모델은 입력 snapshot 불일치 시 거절하고 갱신을 요구 |
| 이어 실행 | source/understanding/hypothesis/jev checkpoints, 원자적 save, NVIDIA output_limit/timeout 시 문맥 축소. 모델·점수 history 보존 |

## 최소 변경 계획

1. `teacher_update.py`에 독립 가설 상태·EvidenceRelation·델타 이력을 추가한다. 기존 모델 JSON은 화면/계획 호환용으로 계속 제공한다.
2. 변경된 근거만 찾는다. A-MEM/개념·사고 코드로 후보를 좁히고, 같은 상태의 질문을 한 Jev 요청으로 묶는다. 실패·낮은 확신은 검토 대기다.
3. 기존 가설은 Jev 관계 판단 후 Python이 갱신한다. 무관은 무변경, 반박은 반례 보존, 범위 변경은 후보다.
4. 새 패턴은 먼저 Jev가 판단한다. 충분히 새로운 작은 근거 묶음만 NVIDIA에 전달하고 후보 하나를 받는다. 다시 Jev로 중복/통합/승격을 판단한다.
5. 웹 기본 흐름을 증분 갱신으로 바꾸고 기존 CLI 전체 생성·점수·모델 함수는 수동 재생성용으로 남긴다. 가설 lifecycle과 대기 작업을 화면·계획에 명시한다.
6. 원문·OCR·노트·그래프는 수정하지 않는다. NVIDIA timeout은 늘리지 않는다. A–I 테스트, 기존 회귀 테스트, 제한된 실제 자료 비교로 검증한다.

전체 재생성은 명시적 수동 실행, 스키마/질문 마이그레이션, 손상 복구, 큰 미해결 충돌, 지정한 benchmark에서만 사용한다.
