"""Bounded verification: synthetic data; credentials only from .env.

Run from the repository root with python scripts/verify_integration_v07.py.
Existing v0.2 results are copied, never modified. Live errors stop the dependent
chain; fixture results stay clearly separate from actual service responses.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_integration_v07 import seed, LLMFixture, JevFixture
from backspace_mvp.pipeline import save
from backspace_mvp.patterns import build_patterns
from backspace_mvp.hypotheses import build_teacher_hypotheses
from backspace_mvp.scoring import build_teacher_scores
from backspace_mvp.teacher_model import build_teacher_model
from backspace_mvp.study_plan import generate_study_plan
from backspace_mvp.llm_provider import create_provider
from backspace_mvp.jev import JevProvider


def main():
    report_path = ROOT / 'output/integration_v07_verification.json'
    report = {'at': datetime.now(timezone.utc).isoformat(),
        'scope': 'synthetic_two_question_pipeline_not_real_teacher_benchmark', 'stages': []}

    def record(stage, result):
        report['stages'].append({'stage': stage, **result})
        save(report_path, report)
        print(json.dumps({'stage': stage, **result}, ensure_ascii=False), flush=True)

    folder = ROOT / 'state/integration_v07/fixture'
    state = seed(folder)
    patterns = build_patterns(state)
    hypotheses = build_teacher_hypotheses(state, provider=LLMFixture(), max_hypotheses=1,
        max_patterns=1, max_questions=2, max_material_items=1)
    scores = build_teacher_scores(state, provider=JevFixture(), max_concepts=2,
        max_hypotheses=1, max_evidence=2)
    model = build_teacher_model(state)
    plan = generate_study_plan(folder / 'teacher_model.json', state, offline=True, max_concepts=2)
    record('fixture_chain', {'status': 'passed', 'question_count': patterns['counts']['questions'],
        'repeated_patterns': patterns['counts']['repeated_patterns'], 'hypotheses': len(hypotheses['hypotheses']),
        'scored_concepts': len(scores['concept_scores']), 'total_concepts': len(model['concept_importance']),
        'tasks': len(plan['tasks']), 'api_calls': 0})

    folder = ROOT / 'state/integration_v07/live'
    state = seed(folder, 'state/teacher_arch_v02/dataset.json')
    patterns = build_patterns(state)
    record('live_pattern_input', {'status': 'passed', 'reused_v02_extraction': True,
        'question_count': patterns['counts']['questions'], 'repeated_patterns': patterns['counts']['repeated_patterns']})
    # Check the service contract once with a very small input before any large call.
    jev = JevProvider(usage_path=folder / 'usage_log.json')
    try:
        probe = jev.score({'observations': ['문항 1은 조건 비교를 요구한다.', '문항 2도 조건 비교를 요구한다.']},
            {'recurrence': {'type': 'score', 'instructions': '제공된 관찰에서 요구 사고의 반복만 판단하세요.',
                'criteria': ['반복이 관찰되지 않음', '한 가지 요구 사고가 두 문항에서 반복됨']}},
            stage='integration_contract_probe')
        save(folder / 'jev_probe.json', probe)
        record('jev_live_contract', {'status': 'passed', 'model': probe['model'], 'requests': 1})
    except ValueError as exc:
        record('jev_live_contract', {'status': 'failed', 'error': str(exc), 'requests': 1})
        # Verify NVIDIA independently; unavailable Jev must not be replaced by fixtures.
    llm = create_provider(task='hypothesis', usage_path=folder / 'usage_log.json')
    llm.fallback = llm.model  # One attempt per stage keeps this smoke run bounded.
    try:
        hypotheses = build_teacher_hypotheses(state, provider=llm, max_hypotheses=1,
            max_patterns=1, max_questions=2, max_material_items=1)
        record('nvidia_live_hypothesis', {'status': 'passed', 'model': hypotheses['generation']['model'],
            'hypotheses': len(hypotheses['hypotheses']), 'requests': len(llm.attempts)})
    except ValueError as exc:
        record('nvidia_live_hypothesis', {'status': 'failed', 'error': str(exc), 'requests': len(llm.attempts)})
        return
    if report['stages'][-2]['status'] != 'passed':
        record('live_score_model_plan', {'status': 'blocked', 'reason': 'jev_service_contract_unavailable'})
        return
    try:
        scores = build_teacher_scores(state, provider=jev, max_concepts=1, max_hypotheses=1, max_evidence=2)
        model = build_teacher_model(state)
        record('live_scores_and_model', {'status': 'passed', 'hypotheses_scored': len(scores['hypothesis_scores']),
            'concepts_scored': len(scores['concept_scores']), 'concepts_total': len(model['concept_importance']),
            'jev_requests_including_probe': len(jev.attempts)})
        planner = create_provider(task='planning', usage_path=folder / 'usage_log.json')
        planner.fallback = planner.model
        plan = generate_study_plan(folder / 'teacher_model.json', state, max_concepts=1, days=2,
            daily_minutes=30, jev=jev, llm=planner)
        record('live_plan', {'status': 'passed', 'tasks': len(plan['tasks']), 'budget': plan['budget'],
            'model': plan['generation']['model'], 'nvidia_requests': len(planner.attempts),
            'jev_requests_including_probe': len(jev.attempts)})
    except ValueError as exc:
        record('live_score_model_plan', {'status': 'failed', 'error': str(exc)})


if __name__ == '__main__':
    main()
