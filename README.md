# Backspace — Teacher Learning Studio

선생님의 자료와 시험에서 개념·사고·평가기준을 추출하고, 이번 시험범위의 학습계획으로 연결하는 로컬 프로토타입입니다.

## 새 설치에서 실행

Python 3.11과 Node.js가 필요합니다. 아래 명령은 이 저장소 폴더에서 실행하세요.

```powershell
python -m venv .venv-ocr
.\.venv-ocr\Scripts\python.exe -m pip install -e '.[ocr,memory,dev]'
npm ci
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# .env의 NVIDIA_API_KEY와 TYPESAFE_API_KEY를 본인의 키로 설정하세요.
.\.venv-ocr\Scripts\python.exe -m backspace_mvp.web --port 8779
```

브라우저에서 http://127.0.0.1:8779 를 열고 ‘내 자료’를 선택하세요. 모델·OCR·메모리의 최초 사용에는 모델 다운로드와 로컬 연산 시간이 필요합니다. Surya는 선택 사항이며 별도 설치·조건 확인이 필요합니다.

이 저장소에는 코드·합성 샘플·화면 자산·설명서·변경 연표만 포함합니다. API 키, 실제 학습자료, 학생 정보, 로컬 OCR 결과·이해 노트·교사 모델·계획·호출 로그는 포함하지 않습니다. 기존 개발 문서의 로컬 `state/`·`output/` 링크는 개발 당시 기록이며 이 저장소에서는 제공되지 않습니다.

## 코드 변경 기록

화면 상단 ‘변경 이력’에서 연표를 확인합니다. 초기 이력은 문서·파일 시각을 바탕으로 복원했으며 정확한 과거 커밋 이력과 다릅니다. 코드 수정 뒤 아래 명령으로 기록을 이어갈 수 있습니다.

```powershell
.\.venv-ocr\Scripts\python.exe -m scripts.update_change_history --title "변경 제목" --summary "사용자에게 달라진 점"
```

자세한 구조와 검증 범위는 아래 개발 문서를 참고하세요. 실제 교사 자료의 분석 정확도와 모든 실패 사례가 해결됐다는 의미는 아닙니다.

---

# Backspace Teacher Intelligence Architecture v0.1

## 웹 작업공간

Jev가 먼저 **기존 내용 재사용 / 추가 추론 / 그래프 필요 여부**를 판단하도록 연결했습니다. 생성된 교사 가설도 지지·반박·근거 강도·적용 범위를 따로 검증합니다. 시간 초과나 답변 길이 제한에서 같은 큰 요청의 시간·토큰을 늘려 반복하지 않습니다. [쉽게 읽는 변경 보고서](docs/jev_control_update.md) · [설정·질문·호출 지도](docs/jev_control_reference.md).

자료 이해 메모리를 **[AGI Research A-MEM](https://github.com/agiresearch/A-mem)**으로 연결했습니다. 기존 OCR 캐시 → 짧은 자연어 Understanding Note → A-MEM 검색·연결·메타데이터 갱신을 먼저 저장하고, 기존 그래프·Teacher Model·Jev·계획을 후속 단계로 유지합니다. 파일의 **이해 노트** 버튼으로 결과를 확인합니다. [쉽게 읽는 변경 보고서](docs/amem_integration.md) · [개발 상세 문서](docs/amem_technical_reference.md).

설치는 `./.venv-ocr/Scripts/python.exe -m pip install -e '.[ocr,memory,dev]'`입니다. 메모리 검색은 다국어 MiniLM의 로컬 ONNX 모델을 사용하며 최초 실행에 약 118MB 모델을 내려받습니다. 새로운 이해 노트는 NVIDIA, 후속 분류·추가 분석 필요 판단은 Jev를 사용합니다. 저장된 노트 조회·검색은 NVIDIA/Jev 호출 없이 동작합니다.

자료·그림 이해 개선: 원문 검토에서 페이지별 **그림 분석**을 실행할 수 있습니다. 이미지와 주변 글자를 함께 분석하고 관찰·관계 해석·불확실성·근거 영역을 저장합니다. 저장된 시각 자료는 이후 학습자료 의미 분석과 관계 검수에도 전달됩니다. [동작·근거·검증 범위](docs/visual_understanding.md).

입력에 **로컬 PaddleOCR 한국어 인식 계층**을 추가했습니다. Native Text와 사진 속 글자를 별도로 읽고, 인식 결과를 먼저 저장한 뒤 의미 분석합니다. 파일당 100MB 업로드와 페이지별 인식 확인·수정을 지원합니다. [OCR 실행·확인·한계](docs/perception.md).

**Black & Lime Learning Studio**로 화면을 개편했습니다. 큰 한국어 타이포와 인터랙티브 사고 지도, 밝은 원문 검토 영역, 날짜별 학습계획을 제공합니다. [새 디자인 미리보기](http://127.0.0.1:8770) · [디자인 검증](docs/design_validation.md). GSAP과 폰트는 로컬에서 제공합니다. **① 과거 학습자료·시험지 → Teacher Model, ② 별도의 이번 시험범위 자료 → 중요도·공부계획**으로 입력을 나눕니다. 개념 지도 클릭, 문항별 사고 탐색, 근거·대안 설명, 파일 업로드, 분석 진행 상태, 계획 완료·메모 저장을 제공합니다.

```powershell
python -m venv .venv-ocr
./.venv-ocr/Scripts/python.exe -m pip install -e '.[ocr]'
npm install
./.venv-ocr/Scripts/python.exe -m backspace_mvp.web --port 8766
```

[웹 열기](http://127.0.0.1:8766) · [웹 사용법·저장 구조·검증 범위](docs/web_app.md). 기본 계획은 API 없이 생성하며, AI 재설계를 선택하면 NVIDIA·Jev를 사용합니다. 키는 서버의 `.env`에 유지합니다. OCR 수정 후 전체 81개 테스트가 통과했습니다. 실제 업로드 PDF 9개, 121페이지의 로컬 읽기가 저장됐으며 OCR 실행 오류는 0개였습니다. 이는 인식 정확도 측정이 아닙니다. 손글씨와 낮은 신뢰도 영역은 검토가 필요합니다. 이 검증에서 NVIDIA·Jev API는 호출하지 않았습니다. 테스트용 설치는 `pip install -e '.[ocr,dev]'`를 사용합니다.

새 고정 설계는 [아키텍처 문서](docs/teacher_intelligence_architecture_v0.1.md)에 있습니다. Teacher Intelligence 70 / Planning 30으로 진행하고 **v0.1 자료 그래프, v0.2 문제별 그래프, v0.3 반복 Pattern Engine, v0.4 Teacher Hypothesis, v0.5 Jev scoring, v0.6 Teacher Model, v0.7 지속 공부계획**까지 제작했습니다. NVIDIA LLM은 추출·생성, Jev는 판단·점수화, Python은 통계·상태 저장을 맡습니다. 실행 모델은 이전 Nemotron 구성으로 지정했습니다. 기존 Teacher Model/계획 실험은 아래에 보존하며 새 7단계의 완성으로 간주하지 않습니다.

v0.7 제작 후 통합 검증을 진행했습니다. **테스트 63개 통과**, 합성 2문항에서 NVIDIA 가설 생성 → Jev 점수화 → Teacher Model → NVIDIA 학습계획 생성과 저장까지 성공했습니다. 실제 교사 자료의 정확도 평가는 남아 있습니다. [생성 결과 보기](output/integration_v07_preview.md), [검증 기록](output/integration_v07_verification.json), [제작·검증 범위](docs/implementation_status.md)를 참고하세요.

비용 없는 테스트는 `python -m unittest discover -s tests -q`로 실행합니다. `python scripts/verify_integration_v07.py`는 이전 v0.2 상태가 있는 로컬 환경에서 합성 샘플의 모의 흐름과 **실제 API 호출**을 제한해 확인합니다. 키는 `.env`에서 읽으며 기존 v0.2 결과를 수정하지 않습니다. `python scripts/summarize_integration_v07.py`는 이번 검증의 저장 결과를 읽어 예시 문서를 갱신하며 API를 호출하지 않습니다.

## v0.7 지속 공부계획

별도 새 시험범위 자료를 Teacher Model과 비교해 상대 중요도·학습 깊이·활동·시간 배정을 만듭니다. 원 판단과 근거를 보존하고 완료 상태·추가 대화/자료 메모·갱신 이력을 저장하도록 제작했습니다.

```powershell
# 별도 새 범위 dataset을 먼저 준비하세요. offline은 계획 단계의 API 호출을 끔.
python -m backspace_mvp generate_plan --model state/teacher_arch_v02/teacher_model.json --materials-state state/new_exam_scope/dataset.json --offline
python -m backspace_mvp update_plan --plan state/teacher_arch_v02/current_plan.json --event-type conversation --note "조건 변화 연습을 더 하고 싶음"
```

출력은 `current_plan.json`입니다. 온라인 모드는 Jev가 새 개념 중요도를 판단하고 NVIDIA가 활동을 생성합니다. [v0.7 사용법·예산·수정 방법](docs/milestone_v0.7.md)을 참고하세요. 이번 실제 호출은 개념 1개에서 과제 2개를 생성했고 60분 배정·30분 미배정을 저장했습니다. 다른 단원의 새 자료로 중요도를 옮기는 품질은 아직 평가하지 않았습니다.

## v0.6 Teacher Model

자료·문항·패턴·가설·Jev 점수를 연결해 개념 중요도, 반복 사고, 평가관 후보와 근거·반례·원 점수를 저장합니다. 미점수화 항목은 null로 유지하고 변경 시 이전 모델을 이력에 보존하도록 구현했습니다. 추가 API 호출은 없습니다.

```powershell
# API 호출 없이 저장 상태를 처리합니다.
python -m backspace_mvp build_teacher_model --state state/teacher_arch_v02/dataset.json
```

출력은 dataset 옆 `teacher_model.json`입니다. [v0.6 계약·갱신 방법](docs/milestone_v0.6.md)을 참고하세요. 이전 실험 보고서는 `build_legacy_teacher_report`로 분리했습니다. 통합 검증 결과는 `state/integration_v07/live/`에 별도 저장했습니다.

## v0.5 Jev 점수화

가설·개별 근거의 지지/반박/근거 강도와 개념의 6개 차원을 독립 Score 질문으로 판단합니다. 원 점수·분포·confidence·기준표·실제 모델·입력 해시를 남기고 Python이 잠정 Teacher Salience를 계산합니다. 미관찰은 null로 보존합니다. 키는 `.env`의 `TYPESAFE_API_KEY`를 사용합니다.

```powershell
# TypeSafe API 사용. 대상 상한을 작게 시작하세요.
python -m backspace_mvp score_teacher --state state/teacher_arch_v02/dataset.json --max-concepts 4 --max-hypotheses 2 --max-evidence 4
```

출력은 `teacher_scores.json`입니다. [v0.5 계약·사용법](docs/milestone_v0.5.md)에 요청 규모·캐시·가중치·한계를 정리했습니다. 

## v0.4 교사 가설

반복 패턴과 관련 자료·문항 근거로 조건부 가설을 생성합니다. 지지/반례 근거, 시험·개념·사고·조건별 적용 범위, 대안 설명과 추가 확인 자료를 저장합니다. 가설은 미검토 후보이며 confidence와 Jev 점수는 아직 채우지 않습니다.

```powershell
# 반복 패턴이 있으면 NVIDIA API 사용.
python -m backspace_mvp build_teacher_hypotheses --state state/teacher_arch_v02/dataset.json
```

출력은 dataset 옆 `teacher_hypotheses.json`입니다. [v0.4 문서](docs/milestone_v0.4.md)에 선택 문맥·캐시·생성 유보·저장 계약을 정리했습니다.

## v0.3 반복 패턴

활성 문항 그래프에서 개념/사고 노드·방향성 연결·경로·분기 포함 부분 그래프를 집계합니다. 사고 코드 구조와 특정 개념을 포함한 구조를 별도로 저장하고 support·분모·시험별 분포·실제 match·원문 근거를 남깁니다. API 호출 없이 Python으로 처리하도록 구현했습니다.

```powershell
# API 호출 없이 저장 상태를 처리합니다.
python -m backspace_mvp mine_patterns --state state/teacher_arch_v02/dataset.json
```

출력은 dataset 옆 `patterns.json`, 이전 버전은 `pattern_history/`입니다. 상세 계약·범위·상한·사용법은 [v0.3 문서](docs/milestone_v0.3.md)에 있습니다.

## v0.2 문제별 그래프 실행

각 문항에 공통 Concept ID, Task, 요구 사고, 이해 증거 후보, 출제 의도 후보를 저장합니다. 원문 위치·SHA-256·인용·추출 confidence와 검토 이력을 보존하며 학생 행동은 `not_observed`입니다. 정답·해설은 문항 번호와 원문 구절을 명시적으로 매핑하고 자료 그래프 빈도에 포함하지 않습니다.

```powershell
python -m backspace_mvp ingest_materials --input data/live_material.txt --state state/v02_demo/dataset.json
python -m backspace_mvp analyze_exam --input data/question_graph_v02/exam.txt --exam-id architecture_v02_demo --answer-key data/question_graph_v02/answer_key.json --state state/v02_demo/dataset.json
python -m backspace_mvp export_question_graphs --state state/v02_demo/dataset.json --out-dir state/v02_demo/question_graphs
```

합성 2문항을 실제 NVIDIA API로 분석하고 개별 JSON 저장까지 확인했습니다. [문항 결과 예시](output/architecture_v02_preview.md), [검증 기록](output/architecture_v02_verification.json), [키 없는 데모·정답 매핑·갱신 방법](docs/milestone_v0.2.md)을 참고하세요. API 검토 통과는 사람이 확인한 과학 정답이나 실제 시험지 정확도 평가가 아닙니다.

## 이번 단계 실행

Python 3.11 이상에서 `python -m pip install -e .`로 설치합니다. 키 없이 실행할 수 있는, 손으로 작성한 합성 자료 2개 데모:

```powershell
python -m backspace_mvp ingest_materials --input data/material_graph_sample.json --state state/teacher_arch_v01_offline/dataset.json
python -m backspace_mvp export_material_graph --state state/teacher_arch_v01_offline/dataset.json --out state/teacher_arch_v01_offline/material_graph.json
python -m unittest discover -s tests -q
```

합성 fixture는 산소 등 6개 개념과 자료 관계 1개를 포함합니다. 산소는 서로 다른 자료 페이지 2개에 등장하고 source_types는 ppt/worksheet입니다. 원문은 `data/material_graph_v01/`에 있으며 ppt는 텍스트 전사를 가정한 분류입니다. **이 데모는 실제 GLM/Jev 결과가 아니고 confidence도 검증용 고정 값입니다.**

실제 자료는 로컬 `.env`의 키를 읽어 NVIDIA Nemotron에 보냅니다. 기본 자료 추출 모델은 `nvidia/nemotron-3.5-lightning-30b-a3b`, 문항 분석·의미 검토는 `nvidia/nemotron-3-super-120b-a12b`입니다. 모델별 키가 없으면 `NVIDIA_API_KEY`를 사용합니다. 기존 `.env`가 다른 모델을 지정하면 `NVIDIA_MATERIAL_MODEL` 및 `NVIDIA_REVIEW_MODEL`을 확인하세요. 키는 소스 코드에 넣지 않습니다. 준비된 `.env`를 `.env.example`로 덮어쓰지 마세요.

```powershell
python -m backspace_mvp ingest_materials --input "sources/lesson.pptx" --material-type ppt --state state/teacher_arch_v01/dataset.json
python -m backspace_mvp ingest_materials --input "sources/worksheet.pdf" --material-type worksheet --state state/teacher_arch_v01/dataset.json
# 예전 계약으로 처리한 같은 원문의 관찰 근거를 보강할 때:
python -m backspace_mvp ingest_materials --input "sources/lesson.pptx" --material-type ppt --state state/teacher_arch_v01/dataset.json --refresh
```

`sources/lesson.pptx`와 `worksheet.pdf`는 경로 예시이며 이 작업 폴더의 sources는 현재 비어 있습니다. 텍스트 PDF, PPTX 텍스트 상자, UTF-8 TXT/MD를 지원합니다. 이미지·스캔·표·굵기·색의 의미를 자동으로 해석하지 않습니다.

자동 출력은 `dataset.json`, `material_graph.json`, 실제 API 호출 시 `usage_log.json`입니다. 내용 변경 시 `material_graph_history/`에 이전 버전을 보존합니다. 같은 원문 재입력은 빈도와 revision을 늘리지 않습니다. 파일 수정본은 새 source로 누적하므로 구판도 포함됩니다. 빈도는 source/page 수이며 단어의 literal 등장 횟수나 Teacher Importance가 아닙니다. 강조가 없는 경우 `not_observed`, 예전 추출의 관찰 누락은 `needs_reextraction`으로 표시합니다. 문항 전용 개념은 자료 그래프 빈도에 포함하지 않습니다.

[material_graph.schema.json](backspace_mvp/schemas/material_graph.schema.json)과 확장한 [dataset.schema.json](backspace_mvp/schemas/dataset.schema.json)은 개념별 관찰·정확한 인용·자기보고 confidence·명시적 강조·조건별 관계를 검증합니다. 원문 출처/SHA/페이지/문자 위치를 역추적할 수 있습니다. 인용 검증과 실제 개념·관계 의미의 정확도 검수는 구별해야 합니다.

Jev 키는 `.env`의 `TYPESAFE_API_KEY`를 사용합니다. 실제 `jev-1.13.0`의 Score 계약·점수 저장·Teacher Salience 조립은 합성 샘플에서 확인했습니다. 판단의 정확성이나 점수 보정 품질을 검증한 것은 아닙니다. 원 점수·분포·기준표·선택 범위를 결과에 보존합니다.

GLM 시간 초과 기록은 [이전 검증 기록](output/teacher_arch_v01_verification.json)에 보존합니다. Nemotron 전환 후 실제 추출·검토·저장 성공 결과는 [결과 보기](output/teacher_arch_v01_nemotron_preview.md)와 [재실행 검증 기록](output/teacher_arch_v01_nemotron_verification.json)에 기록했습니다. 합성 학습자료 1개에서 개념 5개·관계 2개를 저장했으며 관계 유형의 과학적 검수는 남아 있습니다. 코드·상태 처리를 검증한 테스트와 실제 자료 해석 정확도는 서로 다릅니다.

## 이전 문항·계획 실험 (패키지 0.2)

이전 검증에서는 학습자료에 `nvidia/nemotron-3.5-lightning-30b-a3b`, 시험문항과 의미 검토에 `nvidia/nemotron-3-super-120b-a12b`를 사용했습니다. 현재도 자료 추출은 Lightning, 문항 분석·의미 검토는 Super를 사용하며 Jev는 후속 v0.5에서 연동합니다. 키는 `.env`의 `NVIDIA_SUPER_API_KEY` / `NVIDIA_LIGHTNING_API_KEY`에서 읽으며, 모델별 키가 비어 있으면 `NVIDIA_API_KEY`를 사용합니다. 환경변수가 이미 있으면 그 값이 우선합니다. `.env`는 버전 관리에서 제외됩니다.

## 이전 내용 분석·계획 실험

문항 분석은 기존 개념 이름뿐 아니라 관련 **학습자료 원문 블록**을 입력으로 받습니다. 현재 검색은 한국어 부분 문자열과 단어를 사용하는 작은 로컬 검색이며, LightRAG나 임베딩 서버를 설치하지 않습니다. 추정된 그래프 관계를 사실로 취급하지 않고 원문을 직접 검색합니다. 원문 위치·문자 범위·SHA-256·선택 블록·예산 제한 여부·자료집 해시를 기록합니다. 기본 상한은 6블록/10000자이고, 원문 블록을 중간에서 잘라 넣지 않습니다. 검색 결과가 없으면 빈 문맥으로 명시됩니다. 전체 자료를 빠짐없이 검색했다는 뜻은 아닙니다.

문항을 최대 4개의 핵심 수행과 모델이 제시한 6개의 주장으로 묶고 단계별 산출물 검토 항목을 추가하며, 복잡한 시험은 소문항별 입력이 필요할 수 있습니다. 각 문항에는 구체적인 답안 필수 요소, 검증 가능한 주장, 주장별 근거, 사고 단계의 입력·산출물·완료 기준·조건·연습 과제가 저장됩니다. 일반 사고 코드는 공통 태그이며 구체적인 설명 목표를 대신하지 않습니다. 학습자료에 없는 기작은 `domain_knowledge_needs_review`, 이를 사용하는 문항/과제는 `needs_reference_review`로 표시합니다. 학생의 실제 성취는 답안 자료가 없어 `not_observed`입니다.

별도 검토 요청이 자료 관계의 주어·방향·조건·유형, 문항의 주장·단계·연결·누락을 확인합니다. 문항에는 추가로 인용문만 보는 주장별 grounding 검토를 수행합니다. 설명이 논리적이어도 중간 기작이 인용에 없으면 자료 밖 지식으로 표시하고, 부족한 인용을 지지 근거로 저장하지 않습니다. 자료 관계는 AI가 지지한다고 판정한 것만 그래프에 편입하고, 나머지는 체크포인트 manifest에 사유와 함께 남깁니다. 문항에 오류가 있으면 내용 수정 1회와 재검토를 수행하고 계속 실패하면 기존 상태를 보존합니다. AI 검토가 사람의 검수나 과학적 정답 보증은 아닙니다. 동일 모델 검토는 같은 오류를 반복할 수 있습니다. 현재 기본 검토 모델은 Super이고 `.env`의 `NVIDIA_REVIEW_MODEL`로 바꿀 수 있습니다. 검토 오류에는 기본적으로 같은 모델로 한 번 재시도하며 작은 모델로 자동 전환하지 않습니다. 별도 `NVIDIA_REVIEW_FALLBACK_MODEL`을 설정한 경우에만 지정 모델을 사용합니다. 검토 결과의 스키마·항목 번호·완전성을 검사하고, 주장 인용은 원문 블록과 대조합니다. 단계·연결·의도 가설에는 프로그램이 해당 문항 원문을 연결하고, 그 요구가 문항에서 정당한지는 의미 검토에서 확인합니다.

계획은 문항별 구체적인 과제를 그대로 연결하고, 예상 산출물·완료 기준·원문 근거·주의 조건·검토 상태를 담습니다. 같은 활동의 내용과 근거가 같을 때만 완료 상태를 유지합니다. 과제가 바뀌면 `pending`으로 되돌리고 이전 전체 계획은 `plan_history/`에 보관합니다. v0.1 자료나 단계별 산출물까지 포함한 추가 grounding 검토가 없는 이전 분석도 읽을 수 있지만 해당 과제는 `legacy_needs_reanalysis`로 표시합니다. 검토되지 않은 기존 자료 관계도 자동으로 승인하지 않습니다.

기존 원문을 다시 처리하려면 명시적으로 `--refresh`를 사용하세요. 새 분석이 모두 성공한 뒤 해당 원문의 기존 분석을 교체합니다. 단계 캐시는 프롬프트·스키마·모델·출력 상한이 달라지면 재사용하지 않습니다.

```powershell
python -m backspace_mvp ingest_materials --input data/live_material.txt --state state/grounded_v02/dataset.json
python -m backspace_mvp analyze_exam --input data/live_exam.txt --exam-id live_check --state state/grounded_v02/dataset.json
python -m backspace_mvp build_legacy_teacher_report --state state/grounded_v02/dataset.json --out state/grounded_v02/legacy_teacher_report.json
python -m backspace_mvp generate_legacy_plan --model state/grounded_v02/legacy_teacher_report.json --out state/grounded_v02/plan.json
# 같은 원문을 새 자료/분석 계약으로 재분석:
python -m backspace_mvp analyze_exam --input data/live_exam.txt --exam-id live_check --state state/grounded_v02/dataset.json --refresh
```

이 샘플은 합성 1문항이며 실제 시험지의 성능 검증이 아닙니다. 주장이 자료 밖 지식으로 보충되면 표시를 확인한 뒤 참조 자료를 추가해야 합니다. 아직 강한 모델 단독과의 품질 비교, 임베딩/재정렬 검색, Docling 문서 파싱, DSPy 최적화는 구현하지 않았습니다.

[이전 1문항 실행 결과](output/v02_sample_preview.md)와 [당시 검증 기록](output/v02_sample_verification.json)을 보존합니다. 당시에는 명시적으로 `$env:NVIDIA_REASONING_EFFORT='none'`을 사용했고, 기본값 low와의 품질 비교는 하지 않았습니다. 당시 결과에는 양성자 기울기·ATP 합성효소 설명이 빠졌습니다. 위 새 2문항 실행은 정답·해설을 연결해 이 부분을 추출했으며 동일 입력의 모델 비교 실험은 아닙니다. 생성 문장에서 반복된 두 일본어 연결 표현은 한국어로 정규화하며 원문 인용은 바꾸지 않습니다.

## 설치 및 키 없는 데모

Python 3.11 이상, 프로젝트 폴더에서:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m backspace_mvp ingest_materials --input data/sample.json
.\.venv\Scripts\python -m backspace_mvp analyze_exam --input data/sample.json
.\.venv\Scripts\python -m backspace_mvp build_legacy_teacher_report
.\.venv\Scripts\python -m backspace_mvp generate_legacy_plan --model state/legacy_teacher_report.json --exam-format "서술형"
.\.venv\Scripts\python -m unittest discover -s tests -v
```

`data/sample.json`은 합성 6문항입니다. 실제 교사 분석이나 NVIDIA 추론 결과가 아닙니다. JSON 입력은 이미 구조화된 dataset을 검증·병합하며 API를 호출하지 않습니다. 기본 출력은 `state/dataset.json`, `state/legacy_teacher_report.json`, `state/plan.json`입니다.

## 실제 자료와 NVIDIA

`.env.example`을 `.env`로 복사한 뒤 로컬 편집기로 키를 입력하세요. 키를 채팅이나 코드에 넣지 마세요. 실제 모드에서는 추출한 문서 텍스트와 기존 개념 목록을 NVIDIA 서비스로 전송합니다.

```powershell
Copy-Item .env.example .env
# .env를 편집해 NVIDIA_API_KEY를 입력
.\.venv\Scripts\python -m backspace_mvp ingest_materials --input "sources/lesson.pptx" --state state/real/dataset.json
.\.venv\Scripts\python -m backspace_mvp analyze_exam --input "sources/exam.pdf" --exam-id midterm --state state/real/dataset.json
.\.venv\Scripts\python -m backspace_mvp build_legacy_teacher_report --state state/real/dataset.json --out state/real/legacy_teacher_report.json
.\.venv\Scripts\python -m backspace_mvp generate_legacy_plan --model state/real/legacy_teacher_report.json --out state/real/plan.json --exam-format "객관식과 서술형"
```

텍스트 PDF, PPTX 텍스트 상자, UTF-8 TXT/MD를 지원합니다. 구형 PPT, 사진 및 스캔 PDF는 전사 후 입력해야 합니다. PPTX 표·그룹·이미지와 PDF 그림의 의미는 추출하지 않습니다. 텍스트가 없는 페이지는 실패로 처리합니다. 그림이나 표를 쓰는 문제는 의미와 조건을 검토한 전사본으로 입력하세요. 모델의 멀티모달 지원과 별개로 v0.1에는 이미지 입력을 구현하지 않았습니다.

학습자료는 페이지별 작은 개념·관계 계약과 의미 검토로 처리합니다. 시험은 문항 분리 → 원문 검색 → 답안 필수 요소·요구 사고 분석 → 의미 검토와 필요시 내용 수정 → 코드에서 ID·근거 참조·그래프 조립 → 최종 검증·저장 순서입니다. 모델에 전체 dataset 스키마와 긴 ID를 직접 생성하도록 요구하지 않습니다. 모델이 claims에서 빠뜨릴 수 있는 단계별 답안 산출물·조건도 코드가 자동으로 주장 검토에 포함합니다. 대형 PDF 하나를 한 번에 보내지 않습니다.

연결 끊김·HTTP 429/5xx·응답 형식 오류에는 최대 한 번 대체 모델을 사용합니다. 시간 초과·답변 길이 제한에서는 같은 큰 요청을 반복하지 않고 `SemanticReductionRequired`로 호출부에 넘깁니다. 이해 노트·자료 그래프는 원문을 더 작은 구간으로, 가설은 완전한 근거 카드·패턴의 선택 개수를 줄여 최대 두 단계 축소합니다. 문항 경계처럼 안전하게 자르기 어려운 단계는 검토 대상으로 남깁니다. 단계 번호·인용 오류에는 한 번만 수정 요청합니다. 인증 오류·잘못된 요청은 즉시 종료합니다. 완료한 체크포인트와 원래 dataset을 보존하며 실패한 후보를 확정 근거에 편입하지 않습니다. 상세 정책은 [Jev 연동 문서](docs/jev_control_reference.md)를 참고하세요.

원문·해시·교사 범위·ID는 프로그램이 관리합니다. 원문 인용과 문항 내부 단계 번호를 검증하며 다른 문항의 인용을 재사용할 수 없습니다. 개념 이름/alias가 정확히 일치할 때 ID를 재사용하며 새 ID는 이름 해시로 생성합니다. 의미가 같은 다른 표기의 자동 병합은 아직 하지 않습니다. 서버의 JSON schema 강제 기능에 의존하지 않습니다. 동일 내용·종류·시험 ID의 재입력은 API를 다시 호출하지 않습니다. 서로 다른 시험은 별도 `--exam-id`를 사용하세요.

NVIDIA 공식 참조: [Super](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b-infer), [Lightning](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b), [Chat Completions](https://docs.api.nvidia.com/nim/reference/llm-apis). 실제 API 호출은 유효한 키와 모델 접근 권한이 필요합니다.

모델당 네트워크 대기 제한은 `.env`의 `NVIDIA_TIMEOUT_SECONDS`(기본 45초), 전체 출력 상한은 `NVIDIA_MAX_TOKENS`(기본 16000)로 조절할 수 있습니다. 단계별 출력 상한은 분리 2048, 자료 추출 3072, 자료 검토 2048, 문항 분석 4096, 의미 검토 3072, 주장 근거 검토 1536 토큰입니다. `NVIDIA_MATERIAL_MODEL`과 `NVIDIA_EXAM_MODEL`로 작업별 모델을 지정합니다. GLM 기본 대체 모델은 같은 GLM이며 `NVIDIA_FALLBACK_MODEL`로 명시할 수 있습니다. Nemotron을 직접 지정한 경우에는 Lightning과 Super 중 다른 모델로 전환합니다. GLM은 별도 low reasoning으로 호출하며 Super용 none 설정을 적용하지 않습니다. Lightning은 thinking을 끕니다. Super의 기본 설정은 low reasoning과 512 토큰 추론 상한입니다. `NVIDIA_REASONING_EFFORT=none/low/high`로 비교 실험할 수 있으며 none이면 추론 예산을 보내지 않습니다. 검토만 별도로 `NVIDIA_REVIEW_REASONING_EFFORT`를 적용할 수 있고 현재 `.env.example`은 검토에 none을 지정합니다. 지원 값은 [NVIDIA 공식 API 문서](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b-infer)에 따릅니다. 출력 상한·추론 설정은 캐시 식별자와 호출 기록에 반영됩니다. 작은 JSON 추출에서 none을 사용할 때의 품질은 실제 자료로 별도 평가해야 합니다. 원본 NVIDIA.txt와 키는 수정하지 않습니다.

진단 기록은 `output/nvidia_runs/`에 요청 단계·모델·입출력 크기·실행 시간·토큰 수·HTTP 상태·완료 사유·오류 종류를 남깁니다. API 키/헤더/프롬프트/내부 추론 원문은 기록하지 않습니다. 시간 초과, JSON 오류, schema 오류는 구별합니다. 이것만으로 서버 혼잡 여부까지 확정할 수는 없습니다.

한 페이지가 8000자를 넘으면 임의로 자르지 않고 분할 입력을 요청합니다. 여러 페이지에 걸친 문항, 그림이나 공통 지문이 누락된 문항은 전체 문맥을 포함한 텍스트로 정리해 입력하세요. 자동 문항 분리의 누락 여부와 분석의 과학적 정확성은 별도로 검수해야 합니다.

정답 생성과 구조 추출을 분리해 진단하려면:

```powershell
python -m backspace_mvp diagnose_exam --input data/live_exam.txt
python -m backspace_mvp analyze_exam --input data/live_exam.txt --exam-id live_check --state state/nvidia_live/dataset.json
python -m backspace_mvp build_legacy_teacher_report --state state/nvidia_live/dataset.json --out state/nvidia_live/legacy_teacher_report.json
python -m backspace_mvp generate_legacy_plan --model state/nvidia_live/legacy_teacher_report.json --out state/nvidia_live/plan.json
```

일반 정답 생성은 연결·출력 진단이며 자동 정답 검증이 아닙니다. `output/exam_diagnosis.json`은 검수 전 생성 답변입니다.

## 데이터와 분석 규칙

- `schemas/dataset.schema.json`: 교사 범위, 원문 SHA-256와 위치별 텍스트, 공통 concept ID, 자료 관계, 문제별 steps/edges/intent/evidence.
- `schemas/analysis.schema.json`: 누적 Learning Material Network, 독립 Cognitive/Reasoning Network, 공통 Concept 연결, signature와 자료/문항 대응.
- `schemas/plan.schema.json`: revision, dataset hash, 시험 형식, 활동 진행 상태, 누적 이벤트.

데이터 구조 1.1은 기존 1.0 데이터와 호환됩니다. 새 분석 계약은 `grounded-2.2`이며 단계 산출물과 대응 검토 주장의 일치도 검사합니다. 스키마 실제 경로는 `backspace_mvp/schemas/`입니다. 자료 관계는 하나의 누적 MultiDiGraph에 저장하고 문항별 사고 단계 ID는 문제 범위로 분리합니다. 통합 그래프는 연결 조회용이며 통합 그래프를 가로질러 사고 경로를 채굴하지 않습니다.

Teacher Reasoning Signature는 문제 안에서만 edge, 2~3 edge 경로, 3~4 노드의 연결된 induced subgraph를 채굴한 뒤 사고 코드와 방향으로 정규화합니다. support는 해당 패턴이 나타난 서로 다른 문제 수입니다. 기본 반복 기준은 2이고 한 문제에서 여러 번 나타나도 support는 1입니다. 사고 코드 기준 패턴이므로 과학 내용까지 동일한 패턴이라는 뜻은 아닙니다. 문제 수가 많으면 부분그래프 채굴 비용이 커질 수 있습니다.

출제 의도는 실제 교사의 내적 의도를 확정하지 않는 분석 가설입니다. 인용 문자열과 위치가 맞아도 모델의 과학적 해석까지 검증되는 것은 아닙니다. 정확한 원문 인용·스키마·범위·참조 검증과 내용 검수는 구분해야 합니다.

## 계획 지속성과 후속 확장

기본 계획은 문항별 구체적인 요구 사고·연습 과제·완료 기준과 자료 대응으로 생성합니다. 반복 사고 경로는 Teacher Model에 유지합니다. 개인 진단이나 정답률은 사용하지 않습니다. 같은 경로의 계획을 다시 생성하면 revision과 이벤트가 누적되고 동일 활동 ID와 과제 내용 해시가 모두 같을 때만 `pending/in_progress/completed` 상태가 유지됩니다. 기존 계획의 교사 범위가 다르면 덮어쓰지 않습니다.

```powershell
.\.venv\Scripts\python -m backspace_mvp generate_legacy_plan --feedback "다음 회차에 학습 대화 기록 추가 예정"
```

feedback은 기록만 저장합니다. 대화 의미 해석이나 자동 개인화는 아직 구현하지 않았습니다. 추가 자료를 누적 입력 → Teacher Model 재생성 → 계획 재생성하면 새 자료에 맞춰 활동이 갱신됩니다. 기존 활동이 없어지면 현재 목록에서 제거하고 이전 전체 계획은 자동으로 `plan_history/`에 보관합니다. 파일 저장은 원자적 교체 방식이지만 여러 프로세스의 동시 쓰기는 지원하지 않습니다.

`sources/`와 원본 자료 폴더에는 출력할 수 없습니다. 동기화 자료를 변경하지 않으며 기존 데스크톱 Backspace 프로젝트도 변경하지 않았습니다. 데모와 실제 자료는 다른 상태 경로로 구분하세요.

## 아키텍처 참고 조사

[GitHub 레퍼런스와 개선 설계](docs/architecture_references.md)에 7개 저장소의 확인한 구현, 현재 분석의 한계, 적용할 부분과 기준선 비교 실험을 정리했습니다. [커밋·파일 확인 기록](docs/github_reference_snapshot.json)도 포함합니다. 이 문서는 조사와 후속 설계 제안이며, 제안한 개선을 구현하거나 성능을 검증한 결과는 아닙니다.

## 교사 모델 증분 갱신 (2026-10-07)

웹 기본 경로는 새 근거를 Jev로 판단하고 Python이 기존 가설 상태를 갱신합니다. 새 패턴이 필요한 경우만 NVIDIA로 후보 하나를 생성합니다. 기존 가설 생성·점수·모델 CLI와 개념 6차원 점수, 두 자료 공간, OCR/노트/그래프/계획은 유지합니다. 시간 제한을 늘리지 않았습니다.

```powershell
.\.venv-ocr\Scripts\python -m backspace_mvp update_teacher_model --state state\web\workspace\teacher\dataset.json
# 명시적 전체 가설 생성이 필요할 때만 --manual-rebuild 추가
.\.venv-ocr\Scripts\python -m backspace_mvp teacher_feedback --state state\web\workspace\teacher\dataset.json --hypothesis-id <저장된_ID> --kind human_rejected --reason "원문과 해석이 맞지 않음"
```

`teacher_model.json` 옆의 `teacher_model/`에 독립 가설·관계·델타·판단·피드백·대기를 저장합니다. 새 가설 실패는 기존 갱신을 취소하지 않습니다. 불확실한 관계는 ‘무관’으로 변환하지 않습니다. 범위/질문 버전/정책이 변경된 상태나 canonical 손상은 자동 초기화하지 않습니다.

[쉬운 변경 설명](docs/teacher_incremental_update.md), [구현 전 조사](docs/teacher_incremental_mapping.md), [기술 상세](docs/teacher_incremental_reference.md), [제한된 실제 자료 비교](output/teacher_incremental_validation/live/benchmark.json).

## 이해 저장과 후속 분석 재개 (2026-10-07)

이해 노트가 안전하게 저장되면 자료 구간의 ingest는 성공입니다. 검색 연결·Jev·graph·Teacher Model·계획 오류는 별도 단계로 남겨 재개합니다. 웹 자료 목록의 **처리 상태 / 미완료 분석 재개**에서 확인하세요. 자료별 완전한 이해와 일부 구간의 저장을 구분하며, 재개 시 완료한 OCR/노트를 다시 호출하지 않습니다.

[쉽게 읽는 변경 보고서](docs/pipeline_recovery_report.md), [NVIDIA 전체 호출 조사](docs/nvidia_call_audit.md), [실제 9개 PDF 검증](output/pipeline_recovery/real_nine_files.json), 상태 계약: `backspace_mvp/schemas/stage_task.schema.json`.

```powershell
# 기존 인식 결과·노트의 보존과 범위를 검증. API/OCR 호출 없음.
.\.venv-ocr\Scripts\python -m scripts.validate_pipeline_recovery
# 회귀 검증
.\.venv-ocr\Scripts\python -m unittest discover -s tests -v
npm run check
```

queue는 각 자료 공간의 `pipeline_state/tasks`, 상세 오류는 `pipeline_state/diagnostics`에 저장합니다. `/api/jobs`에 `action=resume`, `target=teacher|scope`, 선택적 `task_ids`를 전달할 수 있습니다. 실제 재개는 미완료 단계에 필요한 API를 호출할 수 있습니다. 검증 스크립트의 `--apply-ledger`는 과거 체크포인트 도입용이므로 운영 중 재실행하지 마세요.

진행상황 창은 분석 중에도 **× 닫기 / − 최소화**할 수 있습니다. 닫아도 분석은 계속되며 상단 **진행상황**에서 다시 열 수 있습니다. 같은 작업의 닫기·최소화 선택은 갱신과 새로고침 후에도 유지됩니다. 긴 단계 목록은 펼쳐서 창 안에서 스크롤합니다.

교사 가설 갱신에서는 그래프·이해 노트 모두 Jev 사전 선별을 거칩니다. 일반 교과 설명은 보존하고 관계 요청을 생략하며, 불확실한 판단은 확인 대기로 남깁니다. [쉽게 읽는 최신 개선 보고서](docs/teacher_update_followup_report.md)에 변경 내용·203개 테스트 결과·실제 자료 실험의 한계를 정리했습니다.
