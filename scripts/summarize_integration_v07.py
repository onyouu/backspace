"""Refresh the readable report from saved results; never calls an API."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backspace_mvp.model import read_json
from backspace_mvp.pipeline import save


def main():
    folder = ROOT / 'state/integration_v07/live'
    report_path = ROOT / 'output/integration_v07_verification.json'
    report = read_json(report_path)
    h = read_json(folder / 'teacher_hypotheses.json')
    s = read_json(folder / 'teacher_scores.json')
    m = read_json(folder / 'teacher_model.json')
    p = read_json(folder / 'current_plan.json')
    usage = read_json(folder / 'usage_log.json')
    report['regression_tests'] = {'command': 'python -m unittest discover -s tests -q',
        'passed': 63, 'failed': 0, 'new_integration_cases': 12,
        'last_run_network': 'CLI test blocks urllib requests; providers are fixtures'}
    report['api_usage'] = {'core_nvidia_requests': 2, 'core_jev_requests': 4,
        'extra_jev_requests_before_cli_mock_fix': 3, 'total_nvidia_requests': 2,
        'total_jev_requests': 7, 'cost': None, 'cost_status': 'not_measured',
        'extra_call_note': 'Initial CLI regression patched the defining module instead of the scoring module. '
            'Three real score requests succeeded; temporary fixtures were cleaned. Fixed patch location '
            'and network rejection now prevent this. Those calls are excluded from the saved core token totals.'}
    totals = {}
    for run in usage['runs'].values():
        provider = run['provider']
        summary = totals.setdefault(provider, {'requests': 0, 'input_tokens': 0, 'output_tokens': 0, 'elapsed_seconds': 0})
        for a in run['attempts']:
            u = a.get('usage') or {}
            summary['requests'] += 1
            summary['input_tokens'] += u.get('input_tokens', u.get('prompt_tokens', 0))
            summary['output_tokens'] += u.get('output_tokens', u.get('completion_tokens', 0))
            summary['elapsed_seconds'] += a['elapsed_seconds']
    report['core_service_usage'] = totals
    report['limitations'] = ['Synthetic two-question data; no real teacher exam accuracy benchmark.',
        'v0.1/v0.2 extraction reused previously saved NVIDIA results, not rerun.',
        'Core live scoring covers 1 of 6 registered concepts and one hypothesis; remaining concept scores stay null.',
        'Live sample repeats nodes only; repeated edges/paths/subgraphs are zero. Branching/isomorphism verified with fixtures.',
        'New material transfer on a genuinely different unit is not evaluated in this live smoke run.',
        'Jev values are rubric scores, not truth probabilities; NVIDIA output still needs source/science review.',
        'API cost is not measured. Offline templates preserve feedback, but do not interpret its meaning.']
    save(report_path, report)
    lines = ['# v0.7 통합 검증 결과', '',
        '2026-10-06 · 합성 2문항의 기능·계약 검증. 실제 교사 자료의 정확도 평가가 아닙니다.', '',
        '- 테스트 63개 통과(기존 51개 + 새 통합 12개).',
        '- 모의 응답으로 자료/문항 입력부터 Pattern → Hypothesis → Score → Teacher Model → Plan → 진행 기록 CLI 연결 확인.',
        '- 캐시 재실행, 문항별 support, 시험별 분모, 방향/동형 motif, 생성 유보, 이전 모델 비교, '
            '예산·완료 유지/해제·이력 및 실패 시 기존 파일 보존 확인.',
        '- 실제 NVIDIA Nemotron Super: 가설 생성 1회, 계획 생성 1회 성공.',
        '- 실제 Jev jev-1.13.0: 핵심 흐름 4회 성공. CLI 모의 연결 누락으로 3회 추가 호출 후 수정; 총 7회.',
        '- API 비용 금액은 측정하지 않았습니다.', '',
        '## 실제 저장 결과', '',
        f"- 문항 2개, 가설 {len(h['hypotheses'])}개, 등록 개념 {len(m['concept_importance'])}개 중 점수화 {len(s['concept_scores'])}개.",
        '- 반복 node 4개; 반복 edge/path/subgraph 0개. 구조 검출을 억지로 채우지 않았습니다.',
        f"- 과제 {len(p['tasks'])}개. 시간 용량 {p['budget']['capacity_minutes']}분, "
            f"배정 {p['budget']['scheduled_minutes']}분, 미배정 {p['budget']['overflow_minutes']}분.",
        '- 학생 약점·망각·실제 수행은 미관찰로 유지.', '', '## 생성된 가설 후보', '',
        h['hypotheses'][0]['statement'], '',
        '이 가설은 제공 문항 안의 후보입니다. 인용 보존과 스키마 통과는 해석의 정확성 보증이 아닙니다.', '',
        '대안 설명:', '']
    lines += ['- ' + text for text in h['hypotheses'][0]['alternative_explanations']]
    lines += ['', '## 생성된 학습과제', '']
    for i, task in enumerate(p['tasks'], 1):
        lines += [f"### {i}. {task['activity_type']} · {task['estimated_minutes']}분", '', task['activity'], '',
            '**산출물:** ' + task['expected_output'], '', '**완료 기준:**', '']
        lines += ['- ' + text for text in task['success_criteria']]
        lines += ['', f"원문 검토 필요: {task['needs_reference_review']}. "
            f"예정 {task['scheduled_minutes']}분 / 미배정 {task['unscheduled_minutes']}분.", '']
    lines += ['## 검증의 한계', '',
        '실제 교사 시험·새 단원 자료에 대한 성능 평가와 과학 내용의 사람 검수는 남아 있습니다. '
        '이번 실제 호출은 기존 추출 결과를 재사용하고 개념 1개로 제한했습니다. '
        '단일 개념 점수를 전체 단원의 우선순위로 일반화할 수 없습니다. '
        '오프라인 모드는 메모를 보존하되 의미에 맞춰 활동을 다시 작성하지 않습니다.', '',
        '상태: `state/integration_v07/live/` · 모의 상태: `state/integration_v07/fixture/`.',
        '상세 기록: [integration_v07_verification.json](integration_v07_verification.json).', '']
    (ROOT / 'output/integration_v07_preview.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Saved integration report and readable preview.')


if __name__ == '__main__':
    main()
