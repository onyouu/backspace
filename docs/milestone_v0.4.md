# 구현 단계 v0.4 — Teacher Hypothesis Layer

2026-10-06 업데이트: v0.7 제작 후 합성 샘플 통합 검증을 완료했습니다. [검증 범위와 남은 평가](implementation_status.md), [생성 결과](../output/integration_v07_preview.md)를 참고하세요. 아래 제작 당시의 미검증 표기는 당시 상태입니다.

제작 상태: Python 생성 파이프라인·CLI·JSON 스키마·문서 작성. **실행·테스트·API 호출은 하지 않았다.** 사용자 요청에 따라 v0.7 제작 후 통합 검증한다. 아래 실행 명령과 저장 동작은 구현한 사용 계약이며 확인된 실행 결과가 아니다.

## 흐름

`patterns.json` + `material_graph.json` + 활성 Question Graph → Python으로 입력 snapshot/근거 선택 → NVIDIA LLM의 조건부 가설 생성 → 코드로 근거 ID·지원 문항·적용 범위 연결 → `teacher_hypotheses.json`.

새 단일 생성 단계로 구성한다. 기본 모델은 Nemotron Super이며 `NVIDIA_HYPOTHESIS_MODEL`로 지정한다. `.env`의 모델별 키 또는 `NVIDIA_API_KEY`를 기존 NVIDIA 어댑터가 읽는다. 실제 실행 시 선택한 문항·학습자료의 원문 근거와 패턴 통계를 전송한다. Jev는 호출하지 않는다.

코드는 패턴 스키마·해시·dataset snapshot과 활성 index·graph 버전을 대조하고, 자료 그래프도 dataset에서 다시 확인한다. 오래된 입력은 갱신을 요구한다. 다른 교사 범위나 원문 파일을 출력으로 덮어쓰지 않는다.

## 생성 가설의 계약

각 가설에는 다음이 필수다.

- `statement`: 관찰한 시험·자료의 범위에 한정한 가설 문장.
- `pattern_ids`: 근거가 되는 선택 패턴 ID.
- `supporting_evidence`: 근거 ID와 해당 근거가 가설을 지지한다고 해석한 이유. 인용 패턴마다 서로 다른 문항 2개 이상의 근거를 요구한다.
- `counter_evidence`: 반박 근거 후보와 해석. 입력 문맥에서 찾지 못했으면 빈 배열.
- `counter_evidence_status`: `identified` 또는 `no_counter_identified_in_provided_context`. 전체 자료에 반례가 없다는 뜻이 아니다.
- `applicable_context`: 시험 ID·개념 ID·사고 코드·적용 조건.
- `alternative_explanations`: 최소 2개의 대안 설명. 예: 교과 내용 자체의 특성, 제공된 시험 형식의 영향.
- `next_validation_data`: 다음에 확인할 실제 자료.
- `limitations`: 현재 자료와 해석의 한계.

가설은 `provisional`, 의미 검토는 `unreviewed`, 점수화는 `pending_jev`다. `confidence`는 null로 보존하며 LLM이 판단 확률·교사 중요도·Jev 점수를 생성하지 않는다. 지지/반례 이유에도 `llm_proposed_unscored`를 붙인다.

`structural_statistics`의 support/분모/시험별 분포는 v0.3의 원 통계다. 이 통계는 해당 가설의 참일 확률이 아니고, `supporting_question_ids`는 실제 생성 가설이 인용한 문항 목록이다. 둘을 구별해 보존한다.

`evidence_registry`에 근거 출처·원문 구절·위치·SHA-256·추출 confidence와 원래 노드/문항/자료 ID를 저장한다. 모델은 짧은 `E0`, `P0` 참조만 만들고 저장할 안정된 ID는 Python이 연결한다. 존재하지 않는 참조, 중복 근거, 지지와 반례에 동일 카드 사용, 범위를 벗어난 시험·개념·사고 참조를 거부하도록 구현했다.

원문 인용과 ID가 유효하다는 것은 가설 해석이 옳다는 보증이 아니다. 반례의 의미 판단과 가설의 적절성은 후보 상태이며 v0.5의 Jev 판단 및 이후 실제 자료 검수로 확인한다. 교사의 성격·사적 의도·미래 행동 확률·학생 학습 성취는 추론하지 않도록 프롬프트에 명시한다. 학생 행동은 `not_observed`다.

## 문맥 범위와 생성 유보

기본 상한은 가설 4개, 반복 패턴 12개, 문항 24개, 관련 자료 항목 12개, 입력 packet 48000자다. 부분 그래프→경로→연결→노드 순으로 후보를 선택하고 각 종류 안에서는 support와 ID로 정렬한다. 각 패턴에 최소 2개의 문항을 선택하며 가능하면 다른 시험의 문항을 포함한다. 남는 문항 예산에는 구조적 대비를 위한 다른 문항을 넣는다.

자료는 선택 문항의 개념에 연결된 concept/relation 항목에서 순서대로 선택한다. 전체 자료의 전수 반례 검색이나 의미 검색이 아니다. 조건·관계 assertion·AI 검토 상태를 그대로 전달하고, 같은 구조가 없다는 이유만으로 반례로 삼지 않도록 지시한다.

`selection`은 전체 포함 문항 수와 실제 제공 문항 ID/수, 선택 패턴 ID, 문항 예산 때문에 제외한 패턴, 자료 선택/가능 항목 수, 문맥 크기를 보존한다. 반례 검색 범위는 `provided_context_only`다. 원문을 임의로 자르지 않고 문맥 상한 초과 시 설정 조정을 요구한다.

반복 패턴이 없으면 API를 호출하지 않고 `no_eligible_repeated_patterns`와 빈 가설을 저장하도록 구현했다. 모델도 충분한 근거가 없으면 `abstained`와 유보 사유를 반환할 수 있다. 모든 데이터를 쓰는 강제 가설 생성은 하지 않는다.

## 실행 방법 — v0.7 이후 검증 시 사용

```powershell
python -m backspace_mvp mine_patterns --state state/teacher_arch_v02/dataset.json
python -m backspace_mvp build_teacher_hypotheses --state state/teacher_arch_v02/dataset.json
```

사용자 지정 입력과 상한:

```powershell
python -m backspace_mvp build_teacher_hypotheses --state state/teacher_arch_v02/dataset.json --patterns state/teacher_arch_v02/patterns.json --material-graph state/teacher_arch_v02/material_graph.json --max-hypotheses 4 --max-patterns 8 --max-questions 16
```

기본 출력은 dataset 옆 `teacher_hypotheses.json`이다. `--refresh`는 현재 입력으로 다시 생성한다. 기존 제공자 어댑터의 전송/형식 오류 재시도 정책을 사용하고 v0.4에서 별도 반복 검토·수정 API 단계를 추가하지 않는다. 원문 참조·적용 범위 검사에 실패하면 기존 최종 가설 파일을 유지한다.

유효한 생성 응답만 `teacher_hypothesis_checkpoints/`에 저장하도록 구현했다. 같은 입력 문맥·계약·모델/추론/출력 설정은 재사용한다. 최종 상태가 바뀌면 `teacher_hypothesis_history/`에 전체 이전 버전을 보존하고 revision을 늘린다. 상태에 dataset/패턴/자료 graph 해시와 실제 사용 모델을 기록한다. API usage는 기존 `usage_log.json`에 남긴다. 파일별 atomic replacement이며 동시 쓰기는 지원하지 않는다.

코드: [hypotheses.py](../backspace_mvp/hypotheses.py). 저장 계약: [teacher_hypotheses.schema.json](../backspace_mvp/schemas/teacher_hypotheses.schema.json).

다음 제작은 v0.5 Jev scoring이다. 이 파일의 가설·근거·원 통계를 판단 입력으로 쓰고 원 점수·분포·rubric·모델·입력 해시를 따로 보존한다.
