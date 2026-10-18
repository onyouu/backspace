# NVIDIA 호출 전수 조사 · 2026-10-07

조사 범위는 애플리케이션 Python 코드 전체이다. A-MEM 원본 의존성은 수정하지 않고, Backspace가 연결하는 controller에서 생성 호출을 제거했다. API 키는 환경 설정에서만 읽는다. 이번 감사·테스트·실제 PDF 체크포인트 검증은 외부 API를 호출하지 않았다.

아래 토큰 수는 요청별 출력 상한이다. `NVIDIA_MAX_TOKENS`가 더 작으면 그 값이 적용된다. 문자는 전체 프롬프트 토큰과 같지 않으며, 스키마·안내·이미지는 별도 입력이다.

## 직접 호출과 실제 작업

| 호출 위치 / 작업 | 목적·입력 범위 | 출력 | 분류·대체 가능성 | gate / 실패 / checkpoint |
|---|---|---|---|---|
| `understanding.py`, `ingest_source` → `complete_text` | 최초 자연어 이해. 원문 최대 1,800자 구간 + 페이지 위치·조건. 이미지가 연결되면 vision provider 사용 | 제목·주제·500자 메모, 최대 1,024토큰 | REQUIRED_GENERATION. 의미 요약은 Jev/Python으로 대체하지 않음 | canonical 노트·raw 응답 캐시가 있으면 호출하지 않음. timeout/length는 정확한 원문 위치를 유지하며 최대 깊이 2까지 작은 구간으로 분할. network/format은 해당 구간만 대기. `memory/content_checkpoints`, `memory/notes`, source manifest |
| `staged.py`, `call` → `complete` | 아래 그래프·검토·수정 작업의 공용 실행기. fixture 분기는 실제 NVIDIA 호출이 아님 | 작업별 JSON | 호출기 자체는 역할 없음 | 요청·스키마·버전·모델·토큰 hash로 캐시. 인용 검증 실패는 구체적 피드백을 추가한 수정 프롬프트 한 번만 허용. 네트워크/시간 초과에 동일 요청 자동 반복 없음. `checkpoints/<source_id>` |
| `grounded.py`, `material` → `ex.call` | 원문에서 개념·관계 생성. 노트 기반 구간 900자, 개념 16개·관계 12개. 이전 CLI의 노트 없는 원문 경로는 더 큰 계약 유지 | 그래프 후보, 최대 3,072토큰 | REQUIRED_GENERATION. 판단만으로 새로운 관계 문구를 만들 수 없음 | 저장된 Jev `project_graph=false`이면 해당 노트 그래프 생략. timeout/output_limit은 원문 구간 축소. 캐시 후 파일의 유효 그래프만 commit |
| `grounded.py`, 시각 자료의 `material_review` → `ex.call` | 그림의 화살표·공간·조건과 후보 관계를 독립 검토. 원본 overview/crops 포함 | 시각 판정, 최대 2,048토큰 | OPTIONAL_REASONING. 이미지 의미 해석은 텍스트 Jev에 맡기지 않음 | 이미지 입력이 있는 graph 단위만 실행. Jev graph gate와 동일 checkpoint 적용. 실패는 그래프 task 재개 대상으로 보존 |
| `staged.py`, `segment` → `call` | 시험 페이지에서 완전한 문항 경계를 생성. 페이지 8,000자 초과는 추측하지 않고 검토로 분리 | 문항 분리 JSON, 최대 2,048토큰 | REQUIRED_GENERATION. 불명확한 문항 구조는 생성적 해석 필요 | 시험만 실행. exact source span·번호·겹침은 Python 검증. 페이지 checkpoint |
| `grounded.py`, `question` → `ex.call` | 완전한 문항 한 개 + 관련 학습자료·정답 블록에서 요구 사고 생성 | task·steps·claims·intent 후보, 최대 4,096토큰 | REQUIRED_GENERATION | 문항 분리·검색 완료 후. 원문 인용·ID·조건 검증. 실패는 원문/노트를 취소하지 않음. 문항별 checkpoint |
| `grounded.py`, `semantic_review` → `review_call` | 문항 요구 산출물·채점 기준 누락·과학 오류·단계 연결을 종합 검토. 문항 한 개 + 생성 후보 | 오류·누락 검토 JSON, 최대 3,072토큰 | OPTIONAL_REASONING. 단순 근거 지지는 아래 Jev 경로로 분리. 이 복합 의미 검토는 현재 남아 있는 비용 병목 | 유효 문항 후보가 있을 때만. 최대 2회 의미 검토, 두 번째는 수정 후보 대상. 독립 review checkpoint |
| `grounded.py`, `content_revision` → `ex.call` | 구체적 의미 검토 오류를 반영해 문항 분석 문구 수정 | 수정 후보, 최대 4,096토큰 | REQUIRED_GENERATION, 조건부 | 실제 issues/누락/부정 판정이 있을 때 한 번. 기존 후보+피드백을 포함하므로 동일 transport retry와 구분. revision checkpoint |
| `teacher_incremental.py`, `generate` → `complete` | 기존 가설이 설명하지 못하는 반복 패턴의 새 조건부 가설 한 개. 제한된 독립 문항·자료 카드, 설정된 context 예산 | 후보 가설, 최대 1,800토큰 | REQUIRED_GENERATION | Jev 관련성·novelty gate 이후만. 기존 가설 관계/지지/반박은 Jev. 후보 checkpoint 저장 후 통합. 실패는 기존 교사 갱신 보존, candidate pending |
| `hypotheses.py`, `generate_teacher_hypotheses` → `complete` | 기존 명시적 CLI/수동 전체 가설 생성 경로. 기본 context 48,000자, 가설 기본 4개·최대 8개 | 가설 묶음, 최대 4,096토큰 | REQUIRED_GENERATION, 수동 호환 경로 | 웹 기본은 위 증분 경로. 완전한 근거 카드 단위로 예산 조정하며 캐시. 실패해도 canonical 노트는 보존 |
| `visual.py`, `analyze_page` → `complete` | 사용자가 지정한 복잡한 그림 페이지, PDF overview + 큰 crop 최대 2개 / PPT crop 최대 3개 | 관찰·연결·불확실성, 최대 3,072토큰 | REQUIRED_GENERATION | 명시적 그림 분석. 원본 SHA·page hash로 재사용. 실패해도 OCR/원본은 보존. visual report |
| `study_plan.py`, `generate_study_plan` → `complete` | 점수·Teacher Model·시험범위에서 사람용 공부 행동 작성. context 기본 64,000자, 기본 개념 4개·최대 24개 | 계획 JSON, 최대 8,192토큰 | REQUIRED_GENERATION, 선택형 | offline 기본 경로는 Python으로 0호출. 최신 모델/시험범위·예산 검증 후만. 완료 blueprint/cache 재사용. 실패는 기존 계획 보존, PLANNING 재개 |
| `cli.py`, 수동 진단 → `complete_text` | 명시적 API 연결/정답 실험, 첫 원문 구간 | 짧은 답변, 최대 768토큰 | REQUIRED_GENERATION, 진단 전용 | 자동 파이프라인에서 실행하지 않음. 진단 log 보존 |

## NVIDIA를 쓰지 않는 작업

| 작업 | 이번 구현 |
|---|---|
| A-MEM title/topic/tags/keywords/context | 이미 저장된 이해 노트의 제목·주제 복사. NVIDIA metadata·neighbor evolution 호출 제거 |
| 주제 후보 선택·중복·메모리 연결·graph-needed 판단 | 기존 typed Jev note router. Python이 confident 판정만 반영 |
| 텍스트 material 관계의 원문 지지 | `evidence_review_call` → Jev choice. 주어·목적어·방향·조건을 함께 판정. 낮은 확신은 insufficient, Jev 실패는 task 재개. NVIDIA fallback 없음 |
| question `claim_grounding` | 동일 Jev 경로. 인용 밖 기작을 source-supported로 승격하지 않음. 결정 hash 캐시. 별도 NVIDIA 근거 판정 호출 제거 |
| Teacher 가설 지지/반박/무관·기존 가설 갱신 여부 | 기존 Jev 관계 판단 + Python 증분 ledger. 불확실한 판정을 무관으로 바꾸지 않음 |
| 빈도·노드/edge/path/subgraph·weight·hash·중복·버전 | Python. 새 LLM 호출 없음 |

Jev `choice` 확률은 검증된 사실이나 교사 행동의 실제 확률이 아니다. 원문 연결을 보존한 잠정 판정이다. 이미지 관계 검토와 복합 문항 의미 검토는 여전히 NVIDIA 사용처이며, 해당 생성·검토까지 비용이 없어졌다고 주장하지 않는다.

## 실패·재개 정책

- NVIDIA transport는 한 번만 시도한다. timeout 증가, 출력 증가, 다른 모델에 동일 payload 전송으로 자동 재시도하지 않는다.
- `network_error`, `timeout`, `output_limit`, `invalid_output`, `provider_error`를 구분한다.
- timeout/출력 길이는 지원되는 자료 구간만 의미 단위 축소. 문항 경계를 파괴해서 잘라 재요청하지 않는다.
- 네트워크/출력 오류는 stage의 failed_retryable 기록과 진단 파일을 남긴다. 사용자가 재개하면 실패한 요청 단위부터 다시 시도할 수 있다.
- `NVIDIA_FALLBACK_MODEL` 등 기존 설정 필드는 과거 캐시 호환을 위해 남았지만, transport 실패 뒤 자동 모델 교체 경로는 제거했다.
- 진단: stage/provider/model/error_type/duration/input_size/attempt_count/fallback_used/checkpoint. NVIDIA의 세부 요청 기록은 `output/nvidia_runs`, stage 기록은 각 자료 공간의 `pipeline_state/diagnostics`.

실제 실패 이력과 현재 자료 상태는 [자료 9개 검증 기록](../output/pipeline_recovery/real_nine_files.json)에 있다. 과거 project-call 기록 일부는 특정 PDF에 귀속할 수 없으므로 구분해 저장했다.
