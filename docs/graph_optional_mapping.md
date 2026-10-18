# Graph 의존성 / Source Span 변경 전 조사

기준: 현재 파일과 저장 상태. 사용자 화면의 과거 수치는 현재 수치로 재사용하지 않는다.

| 경로 | 기존 의존성 | 변경 |
|---|---|---|
| web_pipeline.execute | graph_views 성공 → patterns 성공 → update_teacher_model | 이해 노트가 있으면 교사 갱신 진행. Graph/Pattern은 독립 보강 |
| teacher_incremental.update_teacher_model | material_graph, patterns, active question graph snapshot 필수 | 노트가 있는 작업공간의 기본 경로를 primary evidence builder로 연결. 기존 graph-only/수동 경로 유지 |
| teacher_model.build_teacher_model | 패턴·가설·점수·자료 지도 hash 일치 필수 | legacy builder 유지. 새 note-first 모델은 별도 버전/스키마로 동일 teacher_model.json에 저장 |
| grounded.extract_material | concepts+relations+강조+quote 한 요청, 오류면 전체 retry | 작은 concept/relation 계약 + Python span lookup + entry 단위 격리 |
| staged.extract/pages/material | 자료 여러 구간을 전부 성공해야 source commit | 완료 개념·관계의 checkpoint를 유지, 실패 구간은 보강 대기로 기록 |
| grounded.extract_question | task/claim/criterion quote를 모델이 생성 | source span ID wire 계약으로 받고 Python이 기존 검토 계약으로 복원 |
| web.data | pending 파일 때문에 모델 전체 stale | note-first 입력 버전과 별도로 Graph 대기 표시 |
| study_plan | active 가설만 포함 | note-first usable/well_supported 가설의 조건부 근거도 사용, not_ready는 사용 불가 |

Primary evidence: current source snapshot + hash가 맞는 저장 노트 + A-MEM 관련 노트 + Jev 관계 + 기존 가설 + 원문 연결 시험 근거. Graph 없이도 provisional state를 저장한다. 확인되지 않은 가설이 없다는 사실을 숨기거나 ready/usable로 꾸미지 않는다.

SourceSpan은 원문 파일 hash, 인식 결과 버전/hash, locator, offset, 채택 원문, OCR provenance를 묶는다. OCR 변경 시 이전 ID는 유효하지 않다. 문자열 인용은 기존 저장 형식 호환을 위해 Python만 복원한다. 기존 JSON·원문·이해 노트는 삭제/재인식하지 않는다.
