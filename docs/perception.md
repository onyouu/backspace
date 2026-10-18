# 로컬 OCR과 인식 결과 확인

원본 업로드 → 로컬 읽기 → 인식 결과 저장/확인 → NVIDIA 의미 분석 → Python 패턴 → NVIDIA 가설 → Jev 평가 → Teacher Model → 학습계획 순서로 실행한다. 기존 NVIDIA 역할별 모델 설정은 그대로 사용한다.

## 실행

프로젝트 폴더에서 PowerShell:

```powershell
python -m venv .venv-ocr
./.venv-ocr/Scripts/python.exe -m pip install -e '.[ocr]'
./.venv-ocr/Scripts/python.exe -m backspace_mvp.web --port 8766
```

브라우저에서 http://127.0.0.1:8766 을 열고 「내 자료」에서 PDF/PPTX/PNG/JPG/TXT/MD를 올린다. 각 파일은 100MiB(화면 표기 100MB)까지 지원한다. 「자료 읽기 · API 비용 없음」 → 「인식 결과 확인」에서 페이지별 원본 이미지·텍스트·확인 대기 영역을 검토한다. 「수정·확정 저장」 후 의미 분석 버튼을 누른다. 빈 텍스트로 확정하면 그 블록은 제외된다.

Teacher Model용 과거 자료/시험지와 이번 시험범위 자료는 별도 저장한다. 업로드·읽기·텍스트 확인에는 NVIDIA/Jev API를 사용하지 않는다. 의미 분석 이후에는 기존 API 설정을 사용한다. 키는 `.env`에서만 읽으며 브라우저에 전달하지 않는다.

CLI에서 인식만 실행:

```powershell
./.venv-ocr/Scripts/python.exe -m backspace_mvp extract_materials --input '자료.pdf' --out-dir state/perception
./.venv-ocr/Scripts/python.exe -m backspace_mvp extract_materials --input '자료.pdf' --out-dir output/ocr_review --pages 1,3,4
```

`--pages`는 검증용 대표 페이지 선택이다. 선택 캐시는 전체 문서 캐시와 분리된다. 기존 `ingest_materials`, `analyze_exam`도 같은 읽기 계층을 거친다. 확인 내용이 바뀐 자료의 CLI 재분석에는 `--refresh`를 사용한다.

## 저장과 근거

웹은 `state/web/workspace/uploads`에 원본을, `perception/<파일해시-설정해시>/normalized.json`에 읽기 결과를 저장한다. 이미지 영역은 같은 폴더의 내부 ID PNG로 보존한다. 페이지마다 저장하므로 이후 LLM 오류가 나도 읽기 결과가 남는다. 인식 결과는 별도 JSON 스키마로 검증한다.

각 블록에는 원래 인식 텍스트, 현재 텍스트, 위치, 추출 방식, OCR 모델의 신뢰도, 채택 여부, 후보와 수정 이력이 있다. Native Text에는 OCR 점수를 만들어 넣지 않는다. Graph의 인용은 채택된 전사 텍스트의 정확한 구절이어야 한다. **OCR 텍스트는 이미지 원문 그 자체가 아니라 기계 전사**이며, 파일 해시·페이지·이미지·좌표까지 역추적할 수 있다. LLM 확신도와 OCR 신뢰도는 별개의 값이다.

Native Text가 있어도 PDF 이미지·PPT 그림을 따로 검사한다. PDF는 텍스트·이미지 위치를 읽고 이미지 영역을 렌더링하며, PPT는 텍스트·표·그룹을 읽고 잘라 보이는 그림과 배경을 추출한다. PPT 전체를 이미지로 변환하지 않는다. PDF/이미지의 시각 영역을 보존하되 그래프·수식·그림의 의미를 OCR만으로 판정하지 않는다. 네이티브 PPT 차트는 PDF로 내보내야 원본 영역 미리보기를 제공할 수 있다.

불확실한 블록은 확인 대기이며 확정 근거에 포함하지 않는다. 시험지는 불확실한 글자나 확인하지 않은 시각 영역이 있는 페이지를 보류한다. 문항에 필요한 자료를 잘라 추측하는 대신 해당 페이지를 표시한다. 현재 8000자를 초과하는 시험 페이지도 경계 확인 대상으로 보류한다. 학습자료는 블록 경계를 따라 분할하며 빈 페이지는 오류 없이 보존한다. 분석 범위는 전체 업로드 범위보다 작을 수 있고 저장된 coverage/blocked_pages에 남긴다.

개념 표기 오류는 검증된 인용문에서 등록 표기를 찾거나 정확한 인용 구절을 새 표기로 사용해 보정한다. 원문에 없는 인용은 추측해서 채우지 않는다. 보정 내역은 분석 체크포인트 manifest에 남는다.

## OCR 설정과 선택 보조 모델

기본은 CPU의 `PP-OCRv5_mobile_det` + `korean_PP-OCRv5_mobile_rec`이다. 처음 사용할 때 공식 모델 다운로드가 필요하며 다음 실행부터 재사용한다. 모델 용량은 설치 환경 전체의 용량이나 실행 메모리를 뜻하지 않는다.

```env
BACKSPACE_OCR_THRESHOLD=0.80
BACKSPACE_SURYA_ENABLED=0
```

0.80은 초기 확인 기준이며 정확도 보증이나 교사 중요도가 아니다. 낮은 OCR 결과도 보존한다. Surya를 사용할 때는 해당 환경에 `pip install -e '.[surya]'`와 공식 문서의 로컬 실행 백엔드 설치를 수행한 뒤 `BACKSPACE_SURYA_ENABLED=1`로 실행한다. 기본 설치·실행에는 포함하지 않는다. 활성화하면 낮은 신뢰도 글자 영역만 보조 모델에 전달하며, 결과 충돌은 직접 확인한다. 실행 실패도 보존해 표시한다. 두 모델의 점수는 직접 비교하지 않는다.

공식 참고: [PaddleOCR](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html), [한국어 모델](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/text_recognition.en.md), [Surya 실행과 별도 모델 라이선스](https://github.com/datalab-to/surya).

## 검증

구현 이후 API가 차단된 회귀·통합 테스트를 실행한다. 실제 자료 검증은 선택한 페이지의 원본과 인식 결과를 비교해 검증 범위를 기록한다. OCR이 그림의 관계·수학 표기·표 전체의 의미를 정확하게 이해했다고 주장하지 않는다.

```powershell
./.venv-ocr/Scripts/python.exe -m pip install -e '.[ocr,dev]'
./.venv-ocr/Scripts/python.exe -m unittest discover -s tests -v
./.venv-ocr/Scripts/python.exe scripts/verify_perception.py
```

`verify_perception.py`는 웹에 업로드된 첫 PDF 3개의 첫 4페이지를 선택한다. 원본 비교용 영역 이미지와 `output/perception_review/verification.json`을 저장한다. 전체 테스트는 모의 모델 응답을 사용한다. 실제 OCR 검증은 인식의 실행·저장 검증이며, 정답 전사와 비교한 정확도 벤치마크는 아니다. 현재 검증에서는 인쇄된 생물학 용어를 읽었지만 손글씨 오인식과 높은 신뢰도의 잘못된 결과도 관찰됐다. 신뢰도 기준을 통과한 텍스트도 중요한 근거로 사용하기 전에 원본과 비교해야 한다.
