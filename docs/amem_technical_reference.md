# A-MEM를 기반으로 한 자료 이해 메모리 통합

## 변경 전 흐름과 최소 변경 계획

기존: 원본 PDF/PPT/이미지 → Native Text·OCR → 원문 검토 → StagedExtractor의 개념/관계 JSON 및 별도 검수 → 자료·문항 그래프 → Python 반복 패턴 → 교사 가설 → Jev 판단 → Teacher Model → 계획.

새 흐름: 동일한 OCR 캐시 → 짧은 자연어 Understanding Note → **A-MEM MemoryNote·AgenticMemorySystem** → Chroma 의미 검색·관련 노트 연결·메타데이터 evolution → 기존 추출기에 노트 문맥을 제공하여 작은 단위로 secondary graph 생성 → 기존 교사 가설/Teacher Model/계획. Teacher synthesis에는 해당 교사·현재 source/인식 버전의 관련 노트를 먼저 제공하고, 원문 인용과 그래프 기반 반복 수·분모는 그대로 유지한다.

상세 구현 순서: 원본 확인 및 upstream 고정 → A-MEM 클래스 재사용 → 영구 저장소/NVIDIA 어댑터 → Topic·원자료 provenance → 노트 우선 ingest → 기존 Teacher 입력 어댑터 → A~E 검증 및 작은 실제 자료 검증.

## Upstream 고정

- 저장소: https://github.com/agiresearch/A-mem
- commit: `ceffb860f0712bbae97b184d440df62bc910ca8d`
- `third_party/A-mem/`에는 해당 버전의 핵심 Python 파일, README, 설치 명세, MIT LICENSE 원본을 보존한다.
- 실행용 사본: `backspace_mvp/_vendor/amem/`. 원본과 실행용 파일의 차이를 provenance 및 패치 파일로 기록한다.

## 그대로 사용하는 부분

`MemoryNote` 필드·생성, `AgenticMemorySystem.add_note/read/search/search_agentic/analyze_content/process_memory`, 메타데이터 분석 및 evolution 프롬프트·JSON 계약, `ChromaRetriever` 검색 결과·메타데이터 직렬화/복원, `PersistentChromaRetriever` 기반 저장소 구조를 재사용한다.

## 필요한 변경과 어댑터

- upstream 생성자에 retriever/controller 주입 지점만 추가하여 기존 collection reset과 OpenAI 초기화를 피한다. 기본 사용 동작은 그대로 유지한다.
- 사용하지 않는 무거운 import는 실행용 사본에서 제거하고 Ollama의 LiteLLM import는 해당 메서드 실행 때로 이동한다.
- Backspace 영구 Chroma 어댑터는 local embedding과 저장소 경로를 주입하며 데이터 초기화 없이 재개한다.
- 관련 노트 검색의 Chroma 반환 ID를 upstream evolution에서 쓰는 실제 note 인덱스로 매핑한다. 반환 순서가 다른 노트의 context를 잘못 수정하는 일을 막는다.
- NVIDIA metadata/evolution controller는 작은 metadata JSON만 생성한다. Understanding Note 본문은 별도의 자유로운 자연어 출력이다.
- Topic은 노트의 분류 namespace다. 출처·자료 종류·페이지·원문 범위·인식 버전은 별도 metadata로 보존한다. 원문 내용과 기존 노트 본문을 evolution으로 덮어쓰지 않는다.
- Markdown 노트와 Chroma 영구 인덱스, metadata/수정 이력을 함께 보존한다. 완료된 노트는 다음 graph 단계 실패와 관계없이 남는다.

기존 API·JSON schema·Graph·Jev·Planning·100MB 업로드·원본/OCR 보존 기능은 유지한다. 새 메모리는 프로젝트 앱의 자료 메모리이며 Codex 개인 메모리 폴더를 변경하지 않는다.

## 임베딩과 저장

현재 PC의 Windows 실행 정책은 PyTorch의 `c10.dll`을 차단했다. 보안 설정을 변경하지 않고 동일한 다국어 SentenceTransformer를 공식 ONNX 자산으로 실행한다. 모델은 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, `onnx/model_quint8_avx2.onnx`다. [공식 모델](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/tree/main/onnx)은 Apache 2.0이며 최초 다운로드가 필요하다. 모델의 128 token 한도, attention-mask mean pooling과 384차원 정규화를 사용한다. 이는 새 memory framework가 아니라 Chroma embedding function 어댑터다. 긴 노트 후반의 정보가 검색 벡터에 반영되지 않을 수 있다.

NVIDIA 노트 모델은 `NVIDIA_MEMORY_MODEL` 또는 기존 Lightning이며 `.env`에서 키를 읽는다. 별도 OpenAI 키는 필요 없다. 메타데이터/evolution JSON은 작게 유지하고 자유로운 자연어 본문은 JSON 스키마에 넣지 않는다. 첫 노트는 일반적으로 자연어 생성 1회 + 메타데이터 1회, 이후 노트는 evolution 요청이 추가된다. 저장된 단계 재사용은 API를 호출하지 않는다.

자료별로 최대 1,800자 원문 단위를 노트로 만들고, 보조 자료 그래프는 최대 900자·개념 16개·관계 12개 단위로 투영한다. 수리 프롬프트에 이전 전체 JSON을 반복해서 붙이지 않는다. 원문 인용 검증은 유지한다. 시험 문항 분리는 기존 방식이며 노트의 페이지 단위를 실제 단일 문항으로 확정하지 않는다.

저장은 교사 공간 `state/web/workspace/teacher/memory`, 시험범위 공간 `state/web/workspace/scope/memory`를 분리한다. 교사 공간 안의 학습자료와 과거 시험 노트는 함께 검색된다.

```text
memory/
  notes/un_*.md, un_*.json       # 불변 자연어 본문 + 원문/분류/A-MEM 메타데이터
  chroma/                      # 영구 벡터 인덱스, reset 금지
  source_manifests/             # 현재 자료 버전·저장 위치·부분/전체 범위
  source_history/, history/     # 이전 버전과 metadata evolution
  content_checkpoints/          # 완료한 LLM 자연어 응답
  metadata_checkpoints/         # 완료한 metadata/evolution 응답
  topics.json                  # 대주제/중주제/소주제 인덱스
```

현재 원문/인식/시각 해석 버전과 일치하는 노트만 Teacher 문맥으로 선택한다. 검색은 이 자격을 먼저 필터링한 뒤 순위를 매겨 오래된 노트가 현재 노트를 밀어내지 않게 한다. Evolution은 검색 ID와 실제 note 인덱스를 일치시켜 관련 없는 노트 갱신을 막는다. 오류 검토로 rejected가 된 노트는 검색·연결·Teacher 근거에서 제외하며 본문은 삭제하지 않는다. 관련도 거리는 확률이나 교사 중요도가 아니고 현재 임계값 0.8은 정확도 평가로 보정한 값이 아니다.

## 실행

```powershell
./.venv-ocr/Scripts/python.exe -m pip install -e '.[ocr,memory,dev]'
./.venv-ocr/Scripts/python.exe -m backspace_mvp.web --port 8776

# 한 페이지만 먼저 이해. 기존 인식 캐시 경로를 지정한다.
./.venv-ocr/Scripts/python.exe -m backspace_mvp understand_material --input 자료.pdf --perception-dir state/web/workspace/perception --workspace state/teacher/memory --pages p6
# 시험도 같은 교사 memory 공간에 넣는다.
./.venv-ocr/Scripts/python.exe -m backspace_mvp understand_material --input 시험.pdf --kind exam --exam-id midterm --workspace state/teacher/memory
./.venv-ocr/Scripts/python.exe -m backspace_mvp search_memory --workspace state/teacher/memory --query 'Na+ 유입과 탈분극' --source-type exam_question

# 기존 그래프 파이프라인과 함께 사용. 기존 dataset 경로를 유지한다.
./.venv-ocr/Scripts/python.exe -m backspace_mvp ingest_materials --input 자료.pdf --state state/teacher/dataset.json --memory-workspace state/teacher/memory
./.venv-ocr/Scripts/python.exe -m backspace_mvp analyze_exam --input 시험.pdf --exam-id midterm --state state/teacher/dataset.json --memory-workspace state/teacher/memory
# build_teacher_hypotheses는 dataset 옆 memory의 관련 노트를 먼저 받는다.
# mine_patterns → build_teacher_hypotheses → score_teacher → build_teacher_model → generate_plan은 기존 명령 유지.

# 알려진 오류 제외. 원문 수정 후 새 fingerprint의 노트를 만들 수 있다.
./.venv-ocr/Scripts/python.exe -m backspace_mvp review_memory --workspace state/teacher/memory --note-id un_XXXXXXXXXXXXXXXXXXXXXXXXXXXX --status rejected --reason '표 열을 잘못 해석함'
```

웹에서 자료 목록의 **이해 노트 → 이해 노트 만들기**는 해당 파일만 처리한다. 기존 자료 읽기 후 모델 생성에도 자동으로 연결한다. CLI에서 `--memory-workspace`를 생략하면 기존 추출 방식이며 `BACKSPACE_MEMORY_ENABLED=0`은 웹 모델 생성의 자동 노트 단계를 끈다. 노트만 만든다고 교사 모델이나 계획을 생성하지 않는다. 검색/조회는 추론 API 없이 로컬에서 수행한다.

## 검증 결과와 한계

- Python 전체 **112개 테스트 통과**. 기존 104개 회귀 + A-MEM 8개다. A는 복수 원문 단위·Topic·재시작 복원, B/C는 두 번째 자료와 시험 연결 및 올바른 이웃 갱신, D는 관련 노트를 가장 먼저 제공한 가설 생성부터 기존 Jev·Teacher Model·계획까지의 모의 통합, E는 기존 기능 회귀다. 그래프 실패 후 노트 재사용, 부분 범위 확장, 오류 노트 제외·본문 불변도 확인했다. 모의 임베딩과 LLM을 쓰므로 실제 모델의 의미 정확도 측정은 아니다.
- `npm run check` 통과. 실행 중 노트 생성 버튼 차단, 기존 그래프·동작 줄이기·플러그인 실패 처리를 확인했다. `pip check`에서 충돌 없음. Chroma와 PaddleX의 PyYAML 제약을 함께 유지하기 위해 memory extra에서 Kubernetes를 37 미만으로 제한했다.
- 실제 ONNX 실행은 384차원 벡터를 생성했고 한국어 두 관련 문장의 cosine 0.2995가 관련 없는 문장의 0.0610보다 높았다. 하나의 비교이며 검색 품질 benchmark가 아니다.
- 실제 PDF `(3) 02. 기관계의 통합적 작용~` **p6, 15쪽 중 1쪽**에서 기존 인식 결과와 저장된 시각 보고서를 재사용했다. 자연어 노트 생성 4.203초, metadata 요청과 합해 NVIDIA 2회. Chroma 검색과 재실행 재사용 성공. 원본 PDF와 normalized.json의 SHA-256 불변. `output/amem_validation_p6/preview.md`, `verification.json`, `web_notes.json`에 기록했다. 이 잠정 노트 1개만 웹 공간에 추가했으며 추가 원격 호출은 없었다. 미검토 AI 해석으로 표시하며 전체 관계·생물학 정확도 확인을 의미하지 않는다.
- 실제 p7에서는 깨진 표를 잘못 읽어 알부민을 지방 검출 시약으로 해석했다. 과거 긴 응답에는 원문 없는 비례 관계도 있었다. 두 노트 원문을 보존하고 rejected로 표시했으며 Teacher 근거에서 제외한다. `output/amem_validation/review_verification.json`에 실패 분석을 보존했다. p7 보조 그래프 요청은 60.859초 후 시간 초과했다. **A-MEM은 OCR 표 열 복원이나 외부 API 응답 시간을 해결하지 않는다.**
- 전체 9개 PDF/121쪽을 재분석하지 않았고 실제 Teacher Model/Jev/계획을 이번 검증에서 새로 만들지 않았다. 실제 학습자료 이해 품질은 검토가 남는다. 노트는 primary memory이지만 반복 수·지지/반박 근거는 기존 구조화 상태로 확인하므로 실제 Teacher 생성은 유효한 그래프·반복 패턴을 여전히 필요로 한다. 메모리만으로 그래프 검증을 우회하지 않는다.
- 그림 직접 입력은 기존 선택 페이지 시각 분석이 있는 경우에 지원한다. 모든 그림/표를 새로 자동 분석하지 않는다. 시험 노트는 경계 미분리 페이지 단위이고, 실제 문항 연결은 기존 문항 분석이 필요하다. Topic은 LLM 분류 후보이며 표기 통합 품질을 측정하지 않았다.

재현: `python -m unittest discover -s tests -q`, `npm run check`. `scripts/verify_amem.py --live --locator p6 --out output/amem_validation_p6`는 저장된 OCR로 작은 실제 호출을 수행하는 선택 검증이며 `--live` 없이는 실행하지 않는다. `--project-graph`를 추가하면 유료/쿼터 사용 API 요청이 추가될 수 있다.

Upstream 보존 확인: `third_party/A-mem/PROVENANCE.json`의 모든 Git blob SHA-1 검증이 true이고 `backspace.patch`는 실행 사본에만 적용한 차이이다. `memory_system.py`, `retrievers.py`, `llm_controller.py`, `__init__.py`, LICENSE, README, pyproject, requirements의 8개 원본 파일을 그대로 보존했다. `understanding.py`는 Topic/출처/노트 체크포인트·부분 범위, `amem_adapter.py`는 NVIDIA와 영구 Chroma·ID 매핑·본문 보존, `memory_embeddings.py`는 공식 모델의 로컬 실행을 담당한다. 그래프 JSON은 본문을 대신하는 primary representation이 아니라 원문 인용과 통계를 검증하는 secondary representation으로 남는다.
