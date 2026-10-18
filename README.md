# Backspace · Teacher Learning Studio

학습자료에서 개념과 관계를 정리하고, 선생님의 설명·사고 요구에 대한 조건부 가설을 학습계획으로 연결하는 로컬 웹앱입니다.

## 할 수 있는 일

- PDF·PPTX·이미지·텍스트 읽기와 원문 확인
- 자연어 이해 노트, A-MEM 검색 기억, 개념 네트워크 생성
- 지지 근거·반례·적용 조건을 갖춘 Teacher Model 구성
- 집중 주제·기간·공부 시간에 맞춘 계획 생성, 메모 반영, 진도 저장
- 실행용 모델·근거 자료·인식 기록·전체 작업공간 백업을 구분해 다운로드

평가용 시험지는 모델과 계획의 학습 입력에서 제외합니다. 교사 가설은 예측에 활용하되 불확실성과 적용 조건을 유지합니다. 이 저장소는 별도로 훈련한 모델 가중치를 제공하지 않으며, 실제 시험 점수 향상은 아직 검증하지 않았습니다.

## 설치와 실행

Python 3.11과 Node.js가 필요합니다. Windows PowerShell에서 저장소 폴더를 열고 실행하세요.

```powershell
python -m venv .venv-ocr
.\.venv-ocr\Scripts\python.exe -m pip install -e '.[memory,dev]'
npm ci
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv-ocr\Scripts\python.exe scripts/start_backspace.py
```

이후에는 `run_backspace.cmd`로 실행할 수 있습니다. 주소는 **http://127.0.0.1:8786**입니다. 텍스트가 없는 스캔 자료의 로컬 OCR이 필요하면 추가로 설치하세요.

```powershell
.\.venv-ocr\Scripts\python.exe -m pip install -e '.[ocr]'
```

최초 메모리 검색에는 로컬 임베딩 모델 다운로드가 필요합니다. OCR의 GPU 지원과 설치 가능 여부는 환경에 따라 다릅니다. Surya는 선택 기능입니다. 설정과 상세 절차는 [인식 문서](docs/perception.md)와 [메모리 문서](docs/amem_integration.md)를 참고하세요.

## 내 PC를 통한 개인용 외부 접속

PC와 접속할 휴대폰/다른 컴퓨터에 [Tailscale](https://tailscale.com/download)을 설치하고 같은 개인 계정으로 연결한 뒤, PC에서 `run_backspace_remote.cmd`를 실행하세요. 처음에는 안내된 Tailscale 주소에서 HTTPS/Serve 활성화가 필요할 수 있습니다. 표시된 `https://…ts.net` 주소로 접속하면 기존 자료·Teacher Model·계획을 그대로 사용할 수 있습니다.

- PC가 켜져 있고 절전 상태가 아니어야 합니다. 재부팅 후에는 `run_backspace_remote.cmd`를 다시 실행하세요.
- 같은 소유자 계정으로 연결한 기기만 허용합니다. 공개 인터넷 배포 기능인 Funnel은 사용하지 않습니다.
- 원본·생성 결과·ChatGPT 로그인 정보는 PC에 남습니다. 새 ChatGPT 로그인은 해당 PC의 로컬 화면에서 진행하세요.
- 개인 접속 설정은 Git에서 제외된 `state/web/private_access.json`에 저장됩니다. 소유자 계정이나 DNS 주소가 바뀌면 자동으로 권한을 바꾸지 않고 실행을 중단합니다.
- 개인 접속을 중지하려면 `tailscale serve --https=443 off`를 실행하세요. 이후 원격 실행 파일을 열면 다시 연결됩니다.

## AI 연결

**선생님 자료 → Continue with ChatGPT**에서 본인 계정으로 로그인하고 앱 사용을 허용한 뒤 제공되는 모델을 선택할 수 있습니다. 이 연결은 Windows 로컬 앱용이며, 로그인 정보는 프로젝트 밖 `%LOCALAPPDATA%/Backspace/chatgpt/`에 암호화해 보관합니다. 연결 가능 여부와 사용 한도는 계정에서 확인하세요.

Gemini를 사용하려면 `.env`의 `GEMINI_API_KEY`, Jev 판단을 사용하려면 `TYPESAFE_API_KEY`를 설정하세요. 지원되는 다른 공급자와 선택 옵션은 `.env.example`에 있습니다. ChatGPT 연결이 활성화되면 기본 공급자보다 우선하며, 연결 실패나 구독 한도 초과 시 유료 API로 자동 전환하지 않습니다. Jev는 별도 연결입니다. 기본 계획과 저장 자료 조회는 외부 생성 호출 없이 사용할 수 있습니다.

API를 사용하는 분석·계획 생성에서는 선택한 자료의 관련 부분이 해당 공급자에게 전송됩니다. 무료 모델 설정만으로 비용 0원이 보장되지는 않습니다. 계정의 요금과 한도를 확인하세요.

## 사용 순서

1. **선생님 자료:** 학습자료를 올리고 자료 읽기 → 모델 생성을 실행합니다. 비교용 시험지는 별도 종류로 등록합니다.
2. **Teacher Model:** 개념 네트워크와 교사 가설의 근거·조건을 확인합니다.
3. **나의 학습계획:** 이미 분석한 자료 또는 별도로 올린 시험범위를 선택하고 주제·기간·시간을 설정합니다.
4. 과제 카드의 짧은 안내에 따라 공부하고, **완료 기준·근거**에서 자세한 설명을 확인합니다. 메모를 저장한 뒤 AI 계획을 다시 만들면 반영됩니다.

계획은 관련 개념을 우선 선택하며 미포함 개념과 미배정 시간을 표시합니다. 하루 공부 시간은 상한으로 적용하고, 과제가 적으면 남은 날짜는 비워 둡니다. 완료 표시는 학습 진도이며 성취도 점수가 아닙니다. 이전 계획은 이력으로 남기고, 생성 실패 시 기존 계획을 보존합니다.

## 저장과 다운로드

실제 작업공간은 `state/web/workspace/`에 생성됩니다. 이 저장소에는 코드·화면 자산·합성 샘플·문서만 포함하며 실제 학습자료, 시험지, 이해 노트, 생성 모델, 계획, 키와 호출 로그는 포함하지 않습니다.

| 다운로드 | 포함 내용 |
| --- | --- |
| 모델 내려받기 | 실행에 필요한 개념·관계·조건부 가설과 근거 참조 |
| 근거 자료 내려받기 | 중복을 줄인 인용문·출처·관찰 기록 |
| 인식 기록 내려받기 | 페이지별 텍스트·인식 기록 ZIP |
| 전체 백업 내려받기 | 원본과 모델·계획·처리 이력을 포함한 작업공간 ZIP |

실행용 모델과 근거 파일은 `model_hash`와 `evidence_hash`로 짝을 확인합니다. 전체 백업에는 프로그램 코드·실행 환경·`.env`·로그인 정보가 포함되지 않습니다. 복원할 때는 앱을 종료하고 기존 작업공간을 먼저 보존한 뒤 ZIP의 `workspace/`를 `state/web/workspace/`로 옮기세요.

AI 입력에는 관련 근거만 선택하고 중복 인용을 합칩니다. 동일한 입력과 설정의 완료 응답은 재사용하며, 모델·자료·메모·설정이 바뀌면 캐시를 구분합니다.

## 개발 및 검증

```powershell
.\.venv-ocr\Scripts\python.exe -m unittest discover -s tests
npm run check
```

테스트는 상태 보존, 근거 연결, 캐시, 다운로드 및 UI 동작을 검증합니다. 실제 교사 예측의 정확도 검증과는 구분합니다. 개발 당시 로컬 결과 파일을 가리키는 과거 문서의 `state/`·`output/` 링크는 저장소에 포함되지 않습니다.

- [아키텍처](docs/teacher_intelligence_architecture_v0.1.md)
- [메모리 통합](docs/amem_technical_reference.md)
- [처리 실패와 재개](docs/resumable_pipeline_mapping.md)
- [이전 버전 개발 기록](docs/development_readme_20261018.md)

외부 구성요소의 라이선스와 출처는 `third_party/` 및 `backspace_mvp/_vendor/`에 보존합니다.
