# 구현 단계 v0.2 — 시험문제 → Question Graph

고정 아키텍처는 Teacher Intelligence Architecture v0.1이며 이번 작업은 그 두 번째 구현 단계다. Pattern/Teacher Hypothesis/Jev scoring/Teacher Model/새 자료 중요도·계획은 후속 단계에 남긴다. UI와 멀티에이전트는 추가하지 않는다.

## 흐름과 구조

시험 원문 → 번호별 분리 → 관련 학습자료 원문 검색 및 명시적으로 연결한 정답·해설 → Task·요구 사고·답안 기준 후보 추출 → 독립 의미 검토·주장별 원문 지지 검토 → 코드로 ID/연결/근거 조립 → 문제별 파일 저장.

문제마다 다섯 종류의 노드를 저장한다.

| 노드 | 의미 | 상태 |
|---|---|---|
| Concept | 공통 개념 ID를 재사용하고 해당 문제의 사고에 연결 | required |
| Task | 원문에 근거한 이 문제의 요구 | required |
| Reasoning | 조건 비교·원인 추론 등의 코드, 입출력과 수행 조건 | required |
| Evidence of Understanding | 제출할 답안·산출물과 구체적인 기준 후보 | required_candidate |
| Assessment Intent | 위 요구 구조에 근거한 출제 의도 후보 | hypothesis |

각 Task는 필요한 Reasoning으로, Reasoning은 이해 증거 후보로, 이해 증거 후보는 출제 의도 후보로 연결한다. Concept은 해당 사고에 `applied_in`으로 연결한다. 기존 사고 사이의 `precedes/supports/requires/contrasts` 방향을 유지하며 분기 구조를 강제로 선형화하지 않는다.

이해 증거는 학생이 해야 하는 수행이다. 정답·해설을 입력해도 학생 답안이 들어온 것은 아니므로 `actual_student_behavior: not_observed`를 유지한다. 기준과 출제 의도는 모두 후보이며 공식 채점표·교사의 사적 의도라고 확정하지 않는다. 제공된 정답·해설의 저자·진위와 과학 정확성도 자동으로 인증하지 않는다.

LLM은 `confidence`를 각 Task/개념 연결/사고/주장/의도 추출에 자기보고한다. 개념 노드에는 연결별 원 값과 그 최솟값을 보존한다. 이는 추출 확신도의 요약이며 Teacher Importance, 실제 이해 확률, Jev 판단 점수가 아니다.

## 실행

Python 3.11 이상에서 프로젝트 폴더 기준으로 실행한다. `.env`는 실제 키를 가진 로컬 파일이며 공개 예시 파일로 덮어쓰지 않는다. 자료는 Lightning, 문항 추출과 의미 검토는 기본 Super다. 전송·출력 형식 오류 시 추출에는 기존의 대체 모델 한 번을 허용하고, 독립 검토는 기본적으로 같은 Super를 재시도한다. 실제로 응답한 모델은 체크포인트와 usage 기록에서 확인한다.

현재 `.env.example`은 추출의 `NVIDIA_REASONING_EFFORT=low`, 검토만 `NVIDIA_REVIEW_REASONING_EFFORT=none`이다. 기존 low 검토에서 시간 초과가 발생해 검토 요청에 별도 설정을 추가했다. 동일 입력의 reasoning 설정별 정확도 비교는 하지 않았다. none도 내용 검토를 수행하며 그 결과에 기존 검증 규칙을 그대로 적용한다.

```powershell
python -m pip install -e .
python -m backspace_mvp ingest_materials --input data/live_material.txt --material-type worksheet --state state/v02_demo/dataset.json
python -m backspace_mvp analyze_exam --input data/question_graph_v02/exam.txt --exam-id architecture_v02_demo --answer-key data/question_graph_v02/answer_key.json --state state/v02_demo/dataset.json
python -m backspace_mvp export_question_graphs --state state/v02_demo/dataset.json --out-dir state/v02_demo/question_graphs
python -m unittest discover -s tests -q
```

정답·해설 없이도 `analyze_exam`을 실행할 수 있다. `--answer-key`를 생략하면 `not_provided`이며 문항/자료에서 추정한 답안 기준 후보를 저장한다. 부족한 과학 원문 근거는 `needs_reference_review`로 남긴다.

키 없는 구조 검증 데모:

```powershell
python -m backspace_mvp ingest_materials --input data/question_graph_v02/offline_fixture.json --state state/v02_offline/dataset.json
python -m backspace_mvp analyze_exam --input data/question_graph_v02/offline_fixture.json --state state/v02_offline/dataset.json
```

offline_fixture.json은 고정 응답으로 만든 구조·근거 검증 데이터이며 실제 NVIDIA 추론이나 과학 평가의 결과가 아니다. raw `exam.txt`, `answers.txt`와 매핑도 합성 예시이며 실제 교사의 시험지는 아니다.

## 정답·해설 연결 계약

`--answer-key`는 JSON 매핑 파일이다. 예제는 [answer_key.json](../data/question_graph_v02/answer_key.json), 형식은 [answer_key_manifest.schema.json](../backspace_mvp/schemas/answer_key_manifest.schema.json).

```json
{
  "schema_version": "1.0",
  "exam_id": "architecture_v02_demo",
  "entries": [
    {
      "exam_locator": "p1",
      "question_number": "1",
      "source": "answers.txt",
      "locator": "p1",
      "quote": "1. 조건 B의 산화적 인산화에 의한 ATP 생성은 A보다 적다."
    }
  ]
}
```

source는 매핑 파일 기준 경로이며 원본 PDF/PPTX/TXT/MD를 그대로 읽는다. exam_locator는 시험의 페이지/슬라이드 위치, locator는 해설의 위치다. quote는 해설 원문의 정확한 연속 구절이다. 여러 항목을 같은 문항에 연결할 수 있고 전체 해설 없이 일부 문항만 제공해도 된다. 문항별 최대 해설 문맥은 6000자이며 넘으면 임의로 자르지 않고 입력 수정을 요청한다.

원문 검사 후 코드가 해설 block ID와 SHA-256·문자 위치를 만든다. 질문에 전달하는 해설은 그 문항에 매핑한 블록뿐이다. 시험 source에는 문항별 block ID 연결도 저장해 다른 문항의 블록이 섞인 상태를 거부한다. 정답·해설은 `answer_key` 종류로 저장하며 Learning Material Graph의 출현 빈도를 늘리지 않는다.

시험 ID가 다르거나 인용이 원문에 없거나 매핑한 문항이 실제 분리에 없으면 전체 저장을 거부한다. 같은 시험에 정답·해설을 새로 추가하거나 수정하려면 `--refresh`로 재분석한다. 해설 파일의 원문 SHA 변경도 변경된 입력으로 취급한다. `--refresh`만 주면 이전에 명시한 해설 snapshot을 유지한다. 최신 해설을 반영하려면 매핑 파일도 다시 지정한다.

## 저장·재실행·검증

`dataset.json`은 내부 원문과 분석 상태다. 새 문항 계약은 `grounded-2.3`, 구현 milestone은 `0.2`. 기존 1.0/1.1 dataset과 예전 문항은 읽되 새 Task/이해 증거/confidence를 소급 생성하지 않는다. 기존 문항은 index의 `needs_reanalysis`에 표시하고 원문에 `--refresh`를 실행해 새 계약으로 재분석한다.

각 문항은 `question_graphs/q_<ID해시>.json`에 저장하며 `index.json`에서 시험 ID·문항 번호·실제 파일명·revision을 조회한다. 같은 페이지의 번호 1과 다른 시험의 번호 1도 서로 다른 문항 ID다. ID는 원문 SHA·시험 ID·페이지·문항 번호에 기반한다. 파일명에 사용자 문항 번호를 경로로 삽입하지 않는다.

각 노드·연결·검토된 주장의 근거는 source/source_kind/page/locator/question_id/raw_evidence/confidence와 SHA-256·문자 위치를 가진다. 문자 위치는 추출된 페이지 텍스트 기준이고 동일 구절이 반복되면 첫 일치 구간을 사용한다. 자료가 늘어나도 분석 당시의 검색·해설 snapshot을 보존한다. `input_context_hash`로 그 입력 범위를 구분한다. 현재 원문을 다시 해석하려면 `--refresh`를 사용한다.

같은 원문·같은 매핑을 재입력하면 API를 다시 호출하지 않는다. 동일 graph 내용은 파일과 revision을 유지한다. 분석이 바뀌면 이전 파일은 `question_graphs/history/`에 보관한다. 새 분리에서 사라진 문항은 활성 index와 graph 파일에서 제외하고 이력에 보관한다. 향후 Pattern Engine은 활성 index에 있는 문제만 읽어야 한다.

원문 인용/문자 위치/SHA 연결/노드 참조/Task 검토/단계별 주장 검토/해설의 문항 범위를 검사한다. 요구 사고의 산출물도 코드가 별도 검토 주장으로 추가한다. 자료 밖의 과학 지식은 근거 없이 source-supported로 승격하지 않는다. 의미 검토가 실패하면 1회 내용 수정 후 다시 검토하고 계속 실패하면 dataset과 기존 graph를 유지한다.

저장은 파일별 atomic replacement다. dataset이 기준이며 graph 내보내기는 파생 상태다. 중간 중단 후에는 `export_question_graphs`로 재생성한다. 여러 프로세스의 동시 쓰기는 지원하지 않는다. `usage_log.json`에 요청·오류·실제 모델·시간·토큰 사용량을 남기며 키/헤더/프롬프트/내부 추론은 저장하지 않는다.

## 범위와 정확도

텍스트 PDF/PPTX 텍스트 상자/TXT/MD만 처리한다. 스캔·그림·표 의미, 여러 페이지에 이어지는 문항, 문항 번호와 선지/설명 목록이 혼재된 추출물은 필요한 맥락을 검토해 전사해야 한다. 번호가 있는 문항의 시작 위치 누락과 여러 번호를 하나로 합친 경우를 검사하지만 모든 PDF의 전체 문제 개수를 자동으로 검증한 기능은 아니다.

시험/해설이 문항에 정확히 연결됐다는 것과 과학적 해석이 맞다는 것은 서로 다른 검증이다. AI 의미 검토는 사람이 검수한 정답 보증이 아니다. 실제 교사 자료의 정확도 평가·독립 채점·보류 시험 검증은 이후 benchmark에서 수행한다.

현재 실행 결과와 사용한 모델·근거 범위는 [실제 실행 기록](../output/architecture_v02_verification.json), [문항별 미리보기](../output/architecture_v02_preview.md)에서 확인한다.
