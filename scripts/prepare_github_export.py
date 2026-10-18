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
ROOT_FILES = ('.gitignore', '.env.example', 'README.md', 'pyproject.toml', 'package.json', 'package-lock.json', 'run_backspace.cmd', 'run_backspace_remote.cmd')
IGNORES = {'__pycache__', '.git', '.pytest_cache'}


def export(target):
    target = Path(target).resolve()
    if target.exists() or not target.is_relative_to((ROOT / 'output/github_publish').resolve()):
        raise ValueError('새 output/github_publish 하위 폴더를 사용하세요.')
    candidates = [ROOT / name for name in ROOT_FILES]
    for name in FOLDERS:
        candidates += [p for p in (ROOT / name).rglob('*') if p.is_file() and not p.is_symlink()
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
    (target / '.gitattributes').write_text('* text=auto\n*.woff2 binary\n*.png binary\n', encoding='utf-8')
    audit = target.parent / (target.name + '-audit.json')
    audit.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), 'file_count': len(manifest),
        'copied_files': manifest, 'known_key_matches': 0,
        'excluded': ['.env', 'sources/', 'state/', 'output/', 'node_modules/', '.venv-ocr/', '_migration_backup/', '.codex-remote-attachments/']}, indent=2), encoding='utf-8')
    print(json.dumps({'folder': str(target), 'files': len(manifest), 'known_key_matches': 0,
                      'bytes': sum(p.stat().st_size for p in target.rglob('*') if p.is_file())}))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    export(args.out)
