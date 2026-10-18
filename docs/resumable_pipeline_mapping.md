# 수정 전 실제 실행 경로

2026-10-07 코드 확인 후, 구현 변경 전에 기록함.

| 단계 | 현재 코드 / 저장 위치 | 예외가 올라가는 경로 |
|---|---|---|
| 웹 시작 | `web.WebStore.start` → `_work`, `/api/jobs` | `_work`의 단일 except가 모든 예외를 `status=failed`로 바꿈 |
| 원문 인식 | `_read_file` → `perception.extract_document`, workspace/perception | 파일 하나 실패해도 나머지 파일 루프 종료 |
| 이해 생성 | `UnderstandingWorkspace.ingest_source`, memory/content_checkpoints | 자연어 응답 캐시는 있으나 정식 노트가 아닐 수 있음 |
| 메모리 | `BackspaceMemorySystem.add_understanding` → `_persist`, memory/notes | 메타데이터/연결/벡터 인덱스가 노트 정식 저장보다 먼저 실행됨 |
| Jev 라우팅 | `SemanticControl.route_note`, jev_decisions | 노트 저장 전 실행; 실패 fallback도 후속 초기화 실패를 막지 못함 |
| 그래프 | `pipeline.ingest` → `StagedExtractor.extract`, checkpoints | 작은 구간도 실패하면 ingest 예외 → 웹 전체 실패 |
| 패턴 | `patterns.build_patterns`, patterns.json | 상위 예외로 전체 실패 |
| 교사 근거 갱신 | `teacher_incremental.update_teacher_model`, teacher_model/state.json | 개별 판단은 pending이 있으나 상위 오류는 웹 전체 실패 |
| 새 가설 | `TeacherModelUpdateEngine.process_cluster` + candidate callback | 기존 부분 저장/후보 checkpoint는 있음 |
| 모델 조립 | `build_teacher_scores` → `build_teacher_model` | 일부 개념 pending 지원, 조립 오류는 웹 전체 실패 |
| 계획 | `generate_study_plan`, current_plan.json | 상위 예외로 전체 실패 |
| NVIDIA | `nvidia.NvidiaProvider.complete/complete_text` | timeout/length는 semantic 축소, 네트워크/잘못된 JSON은 alternate 재시도 가능 |
| 재개 | 원문·content·staged·Jev·증분 교사 각각 캐시 | 전체 stage/task queue는 없음 |
| 화면 | `web_static/app.js:drawJob/trackJob`, `views.js:perceptionFile` | done/failed만 표시, 실패한 후속 단계와 성공한 이해를 구분 못함 |

대표 실패 경로: `_work` → `pipeline.ingest` → `UnderstandingWorkspace.ingest_source` → Jev/A-MEM 초기화·metadata·index 또는 `StagedExtractor.extract` → 예외 → `_work.except` → 전체 failed. 원문과 일부 캐시는 남지만 사용자에게 쓸 수 있는 이해와 미완료 그래프가 분리되어 보이지 않는다.

수정 원칙: MD 본문 + SHA 검증 JSON + source manifest를 원자적으로 각각 저장한 뒤 UNDERSTANDING을 complete로 기록한다. 저장 장치 오류는 성공으로 간주하지 않는다. 이후 라우팅·색인·그래프는 별도 task이며 이전 본문을 변경하지 않는다.
