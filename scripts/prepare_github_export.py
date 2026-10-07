"""Build a source-only GitHub export; never copy runtime data or credentials."""
import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ('backspace_mvp', 'data', 'docs', 'scripts', 'tests', 'third_party')
ROOT_FILES = ('.gitignore', '.env.example', 'README.md', 'pyproject.toml', 'package.json', 'package-lock.json')
IGNORES = {'__pycache__', '.git', '.pytest_cache'}


def export(target):
    target = Path(target).resolve()
    if target.exists() or not target.is_relative_to((ROOT / 'output/github_publish').resolve()):
        raise ValueError('새 output/github_publish 하위 폴더를 사용하세요.')
    candidates = [ROOT / name for name in ROOT_FILES]
    for name in FOLDERS:
        candidates += [p for p in (ROOT / name).rglob('*') if p.is_file()
                       and not IGNORES.intersection(p.relative_to(ROOT).parts)
                       and p.suffix not in ('.pyc', '.log', '.tmp')]
    # Report paths only; actual key values are never printed or written to the export.
    secrets = [str(value).encode() for key, value in dotenv_values(ROOT / '.env').items()
               if value and (key.endswith('API_KEY') or key.endswith('TOKEN')) and len(value) >= 8]
    forbidden = re.compile(rb'(?:nvapi-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})')
    flagged = [str(p.relative_to(ROOT)) for p in candidates
               if any(secret in p.read_bytes() for secret in secrets) or forbidden.search(p.read_bytes())]
    if flagged:
        raise ValueError('키로 의심되는 값이 포함된 파일: ' + ', '.join(flagged))
    target.mkdir(parents=True)
    manifest = []
    for original in sorted(candidates):
        relative = original.relative_to(ROOT)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
        manifest.append({'path': relative.as_posix(), 'sha256': hashlib.sha256(original.read_bytes()).hexdigest()})
    ignore = target / '.gitignore'
    ignore.write_text(ignore.read_text(encoding='utf-8') + '\n# Private local inputs and generated files\n.env.*\n!.env.example\n/sources/\n/학습자료/\n/시험지/\n*.pdf\n*.pptx\n.pytest_cache/\n.DS_Store\n', encoding='utf-8')
    introduction = '''# Backspace — Teacher Learning Studio

선생님의 자료와 시험에서 개념·사고·평가기준을 추출하고, 이번 시험범위의 학습계획으로 연결하는 로컬 프로토타입입니다.

## 새 설치에서 실행

Python 3.11과 Node.js가 필요합니다. 아래 명령은 이 저장소 폴더에서 실행하세요.

```powershell
python -m venv .venv-ocr
.\\.venv-ocr\\Scripts\\python.exe -m pip install -e '.[ocr,memory,dev]'
npm ci
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# .env의 NVIDIA_API_KEY와 TYPESAFE_API_KEY를 본인의 키로 설정하세요.
.\\.venv-ocr\\Scripts\\python.exe -m backspace_mvp.web --port 8779
```

브라우저에서 http://127.0.0.1:8779 를 열고 ‘내 자료’를 선택하세요. 모델·OCR·메모리의 최초 사용에는 모델 다운로드와 로컬 연산 시간이 필요합니다. Surya는 선택 사항이며 별도 설치·조건 확인이 필요합니다.

이 저장소에는 코드·합성 샘플·화면 자산·설명서·변경 연표만 포함합니다. API 키, 실제 학습자료, 학생 정보, 로컬 OCR 결과·이해 노트·교사 모델·계획·호출 로그는 포함하지 않습니다. 기존 개발 문서의 로컬 `state/`·`output/` 링크는 개발 당시 기록이며 이 저장소에서는 제공되지 않습니다.

## 코드 변경 기록

화면 상단 ‘변경 이력’에서 연표를 확인합니다. 초기 이력은 문서·파일 시각을 바탕으로 복원했으며 정확한 과거 커밋 이력과 다릅니다. 코드 수정 뒤 아래 명령으로 기록을 이어갈 수 있습니다.

```powershell
.\\.venv-ocr\\Scripts\\python.exe -m scripts.update_change_history --title "변경 제목" --summary "사용자에게 달라진 점"
```

자세한 구조와 검증 범위는 아래 개발 문서를 참고하세요. 실제 교사 자료의 분석 정확도와 모든 실패 사례가 해결됐다는 의미는 아닙니다.

---

'''
    readme = target / 'README.md'
    readme.write_text(introduction + readme.read_text(encoding='utf-8'), encoding='utf-8')
    (target / '.gitattributes').write_text('* text=auto\n*.woff2 binary\n*.png binary\n', encoding='utf-8')
    audit = target.parent / (target.name + '-audit.json')
    audit.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), 'file_count': len(manifest),
        'copied_files': manifest, 'known_key_matches': 0,
        'excluded': ['.env', 'sources/', 'state/', 'output/', 'node_modules/', '.venv-ocr/']}, indent=2), encoding='utf-8')
    print(json.dumps({'folder': str(target), 'files': len(manifest), 'known_key_matches': 0,
                      'bytes': sum(p.stat().st_size for p in target.rglob('*') if p.is_file())}))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    export(args.out)
