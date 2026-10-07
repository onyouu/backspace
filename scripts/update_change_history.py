"""Maintain an append-only public timeline and a local code fingerprint snapshot.

Run after a code change with --title/--summary, or --scan for detected file changes.
Historical milestones use documented file creation times, never invented commits.
"""
import argparse
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from backspace_mvp.model import read_json
from backspace_mvp.pipeline import save

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
HISTORY = ROOT / 'backspace_mvp/web_static/change-history.json'
SNAPSHOT = ROOT / 'state/development_history/code_snapshot.json'

# Each description is grounded in the corresponding implementation report/code.
MILESTONES = [
    ('backspace_mvp/analysis.py', '시작', '로컬 Teacher Agent의 첫 코드',
     '자료와 문항을 구조화해 저장하는 Python 프로토타입을 시작했습니다.', ['backspace_mvp/analysis.py', 'backspace_mvp/model.py']),
    ('backspace_mvp/nvidia.py', 'AI 연결', 'NVIDIA API와 작은 CLI 연결',
     '로컬에서 자료 분석을 실행하고 결과를 저장하는 흐름을 마련했습니다. API 키는 환경 파일에서 읽습니다.', ['backspace_mvp/nvidia.py', 'backspace_mvp/cli.py']),
    ('backspace_mvp/staged.py', '안정화', '분석을 나눠 저장하는 구조',
     '자료 분석을 작은 단계로 나누고, 저장된 중간 결과를 재사용하는 기반을 추가했습니다.', ['backspace_mvp/staged.py']),
    ('docs/teacher_intelligence_architecture_v0.1.md', 'v0.1', '자료를 누적 개념 지도로',
     '학습자료는 하나의 누적 지도, 시험은 문항별 사고 지도로 나누는 구조를 고정했습니다. Teacher Intelligence 70 / Planning 30 방향을 잡았습니다.', ['backspace_mvp/materials.py', 'docs/teacher_intelligence_architecture_v0.1.md']),
    ('docs/milestone_v0.2.md', 'v0.2', '문항별 요구 사고 분석',
     '각 문제의 개념·요구 행동·사고 과정·답안 기준·출제 의도 후보를 별도 지도로 저장합니다. 학생이 실제로 한 행동과 문제에서 요구하는 행동을 구분합니다.', ['backspace_mvp/question_graphs.py']),
    ('docs/milestone_v0.3.md', 'v0.3', '여러 문제에서 반복되는 사고 찾기',
     'Python이 반복되는 노드·연결·경로·분기 구조를 집계하도록 했습니다. 같은 문항 안의 반복과 여러 문항의 지지를 구분합니다.', ['backspace_mvp/patterns.py']),
    ('docs/milestone_v0.4.md', 'v0.4', '교사의 평가 방식에 대한 가설',
     '반복 패턴과 자료 근거를 바탕으로 교사 가설을 만듭니다. 지지 근거·반례·적용 조건·다른 설명을 함께 남깁니다.', ['backspace_mvp/hypotheses.py']),
    ('docs/milestone_v0.5.md', 'v0.5', 'Jev로 중요도와 근거 점수화',
     '개념 중요도와 가설 지지·반박을 Jev가 판단하도록 연결했습니다. 요약 점수와 함께 원 점수·분포·판단 근거를 보관합니다.', ['backspace_mvp/jev.py', 'backspace_mvp/scoring.py']),
    ('docs/milestone_v0.6.md', 'v0.6', '구조화된 Teacher Model',
     '개념 중요도·주요 사고 패턴·평가 가설을 하나의 교사 모델로 묶었습니다. 아직 산정하지 않은 점수는 빈 값으로 남깁니다.', ['backspace_mvp/teacher_model.py']),
    ('docs/milestone_v0.7.md', 'v0.7', '새 시험범위로 학습계획 만들기',
     '교사 모델과 이번 시험범위 자료를 따로 연결해 공부 깊이와 일정을 만듭니다. 완료 상태·메모·계획 변경 이력을 저장합니다.', ['backspace_mvp/study_plan.py']),
    ('docs/implementation_status.md', '검증', 'v0.1~v0.7 통합 검증 기록',
     '합성 자료로 전체 파이프라인을 연결하고 실제 NVIDIA·Jev 호출을 제한적으로 확인했습니다. 실제 교사 시험 정확도 평가는 별도 과제로 남겼습니다.', ['docs/implementation_status.md']),
    ('docs/web_app.md', '웹', '학생용 웹 작업공간',
     '선생님 모델을 만드는 과거 자료 공간과 이번 시험 준비 공간을 나눴습니다. 업로드부터 모델 탐색·계획까지 브라우저에서 사용할 수 있게 했습니다.', ['backspace_mvp/web.py', 'backspace_mvp/web_static/app.js']),
    ('docs/perception.md', '자료 읽기', '로컬 OCR과 원문 검토',
     'PDF·PPT의 텍스트와 이미지 읽기를 의미 분석 앞에 분리했습니다. 원본·최초 인식·수정 이력을 보존하고, 파일당 업로드 제한을 100MB로 늘렸습니다.', ['backspace_mvp/perception.py', 'backspace_mvp/web_static/perception.js']),
    ('docs/design_validation.md', '디자인', 'Black & Lime 작업공간',
     '블랙·라임 디자인과 GSAP 전환, 인터랙티브 사고 지도를 적용했습니다. 모바일 화면과 원문 검토·계획 작업 흐름을 확인했습니다.', ['backspace_mvp/web_static/motion.js', 'backspace_mvp/web_static/graph.js']),
    ('docs/error_audit_2026-10-06.md', '안정화', '원문 인용 오류 조사',
     '원문에 없는 인용과 개념 추출 실패 기록을 조사했습니다. 인용을 임의로 만들어 통과시키지 않고, 실제 원문과의 대응을 확인하도록 했습니다.', ['docs/error_audit_2026-10-06.md']),
    ('docs/UI_REFERENCES.md', '디자인', '더 간결한 AI 작업 화면',
     '기술 기업의 AI UI를 참고해 설명을 줄이고, 정돈된 자료 목록과 작업 중심의 화면으로 방향을 다듬었습니다.', ['backspace_mvp/web_static/studio.css', 'docs/UI_REFERENCES.md']),
    ('docs/visual_understanding.md', '그림 이해', '글자뿐 아니라 도식과 그림도 분석',
     '자료의 그림·표·도식에 이미지 분석을 연결하고, 어느 영역을 이해했는지 원문 좌표와 함께 저장합니다. 이미지 해석과 원문 인용을 구분합니다.', ['backspace_mvp/visual.py']),
    ('docs/amem_integration.md', '메모리', '자료를 이해 노트로 기억',
     '자료에서 이해한 내용을 출처가 있는 짧은 노트로 저장하고 관련 노트를 다시 찾도록 A-MEM을 연결했습니다. 요약만으로 교사의 중요도를 확정하지 않습니다.', ['backspace_mvp/understanding.py', 'backspace_mvp/amem_adapter.py']),
    ('docs/jev_call_mapping.md', 'AI 연결', 'Jev 호출 위치 점검',
     '어느 단계에서 Jev가 호출되고, 언제 점수화가 생략되거나 대기하는지 연결 구조를 정리했습니다.', ['docs/jev_call_mapping.md']),
    ('docs/jev_control_update.md', '비용·속도', 'Jev가 느린 분석의 필요성을 먼저 판단',
     'Jev를 점수화뿐 아니라 분류·중복·추가 분석 필요성 판단에도 사용합니다. 큰 요청을 그대로 반복하거나 NVIDIA 시간 제한부터 늘리는 방식을 줄였습니다.', ['backspace_mvp/semantic_control.py', 'docs/jev_control_update.md']),
    ('docs/teacher_incremental_update.md', '교사 모델', 'Teacher Model을 조금씩 갱신',
     '새 자료마다 가설 전체를 다시 쓰는 대신 지지·반례를 기존 가설에 붙입니다. 기존 가설로 설명되지 않는 반복 패턴이 있을 때 새 가설을 제안합니다.', ['backspace_mvp/teacher_incremental.py', 'backspace_mvp/teacher_update.py']),
    ('docs/pipeline_recovery_report.md', '복구', '후속 실패가 저장된 노트를 지우지 않도록',
     '노트 저장과 검색·Jev·지도·모델·계획의 완료 상태를 분리했습니다. 일부 단계가 실패해도 저장 결과를 남기고, 미완료 단계부터 이어갑니다.', ['backspace_mvp/stage_state.py', 'backspace_mvp/web_pipeline.py']),
    ('docs/error_recovery_followup.md', '안정화', '실패 기록과 응답 시간 처리 개선',
     '이전 실패 기록에서 즉시 멈추던 작은 분석 구간을 다시 시도하도록 했습니다. 응답 전체의 시간 예산을 적용하고 읽기 완료와 분석 완료 안내를 구분했습니다.', ['backspace_mvp/staged.py', 'backspace_mvp/nvidia.py']),
    ('docs/runtime_verification_2026-10-07.md', '검증', '실제 실행 화면과 저장 상태 점검',
     '실제 서버와 저장 노트를 확인하고, 진행상황 창의 닫기·최소화·재열기를 점검했습니다. 테스트 통과와 실제 자료의 분석 완료를 구분해 기록했습니다.', ['docs/runtime_verification_2026-10-07.md']),
    ('docs/retry_runtime_and_file_exclusion_2026-10-07.md', '안정화', '수정된 서버 적용과 안내자료 제외',
     '수정 전 서버로 반복 분석하던 문제를 확인해 새 실행 주소에 수정본을 적용했습니다. 요청한 영어 안내자료를 목록·활성 근거에서 제외하고 원본은 보관했습니다.', ['backspace_mvp/web.py', 'scripts/exclude_unprojected_file.py']),
]


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, KST).isoformat(timespec='seconds')


def seed_history():
    entries = []
    for reference, category, title, summary, files in MILESTONES:
        path = ROOT / reference
        if not path.is_file():
            continue
        stat = path.stat()
        entries.append({'id': 'restored-' + hashlib.sha256(reference.encode()).hexdigest()[:16],
            'at': iso(getattr(stat, 'st_birthtime', stat.st_ctime)), 'category': category,
            'title': title, 'summary': summary, 'time_basis': '복원 기록 · 문서 생성 시각' if reference.startswith('docs/')
                else '복원 기록 · 첫 코드 파일 생성 시각',
            'reference': reference, 'files': [file for file in files if (ROOT / file).is_file()]})
    return {'version': 1, 'timezone': 'Asia/Seoul', 'entries': entries}


def scan_files():
    result = {}
    for folder in ('backspace_mvp', 'scripts', 'tests'):
        for path in (ROOT / folder).rglob('*'):
            if path.suffix not in ('.py', '.js', '.cjs', '.css', '.html', '.json') or not path.is_file():
                continue
            if '__pycache__' in path.parts or path == HISTORY:
                continue
            result[path.relative_to(ROOT).as_posix()] = {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'modified_at': iso(path.stat().st_mtime)}
    return result


def update_history(title=None, summary=None, files=()):
    history = read_json(HISTORY) if HISTORY.exists() else seed_history()
    current = scan_files()
    previous = read_json(SNAPSHOT)['files'] if SNAPSHOT.exists() else None
    changed = sorted(key for key in set(current) | set(previous or {})
                     if previous is not None and current.get(key, {}).get('sha256') != previous.get(key, {}).get('sha256'))
    selected = list(files) if files else changed
    if title or changed:
        if not previous and not selected:
            raise ValueError('첫 기록에는 변경 파일을 지정하세요. 과거 전체 코드를 새 변경으로 기록하지 않습니다.')
        for file in selected:
            if file not in current and file not in (previous or {}):
                raise ValueError('추적 대상 코드 파일이 아닙니다: ' + file)
        at = datetime.now(KST).isoformat(timespec='seconds')
        history['entries'].append({'id': 'change-' + uuid4().hex, 'at': at, 'category': '업데이트',
            'title': title or f'코드 {len(changed)}개 파일 변경',
            'summary': summary or '이전 기록과 비교해 변경된 코드를 발견했습니다. 파일별 수정 시각은 아래에서 확인할 수 있습니다.',
            'time_basis': '변경 기록 시각 · 파일별 수정 시각 별도',
            'files': [{'path': file, **(current.get(file) or previous[file]),
                       'change': 'removed' if file not in current else 'modified' if previous and file in previous else 'recorded'}
                      for file in selected]})
    history['entries'].sort(key=lambda entry: entry['at'])
    history['updated_at'] = datetime.now(KST).isoformat(timespec='seconds')
    save(HISTORY, history)
    save(SNAPSHOT, {'files': current, 'recorded_at': history['updated_at']})
    return len(history['entries'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--title')
    parser.add_argument('--summary')
    parser.add_argument('--files', nargs='*', default=[])
    parser.add_argument('--scan', action='store_true', help='Record detected changes since the saved snapshot')
    args = parser.parse_args()
    print(f'{update_history(args.title, args.summary, args.files)} timeline entries saved')
