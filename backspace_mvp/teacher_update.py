"""Jev judgments + Python state transitions; generation is a separate bounded callback.

state.json is the atomic transaction checkpoint. Independent records are repairable
projections of that checkpoint, never the authoritative partial write of a transaction.
"""
import copy
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from .model import read_json
from .pipeline import digest, save, writable
from .semantic_control import SemanticControl
from .teacher_questions import (RELATION_VERSION, PREFILTER_VERSION, NOVELTY_VERSION,
    INTEGRATION_VERSION, SUFFICIENT_VERSION, relation_questions, prefilter_questions,
    novelty_questions, integration_questions, sufficient_questions)

VERSION = 'teacher-incremental-v1'
LIFECYCLES = ('candidate', 'active', 'weak', 'contested', 'retired', 'rejected')
FEEDBACK = ('human_confirmed', 'human_rejected', 'human_narrowed_scope',
            'observed_in_exam', 'not_observed_in_exam', 'contradicted_by_exam')
DEFAULT_POLICY = {'version': VERSION, 'max_related_hypotheses': 4, 'max_changed_evidence': 24,
    'max_clusters': 3, 'max_cluster_questions': 4, 'max_cluster_materials': 2,
    'max_context_chars': 15000, 'minimum_questions': 2, 'minimum_sources': 2,
    'minimum_coverage': 1.0, 'strong_contradiction': 2.0}


def now():
    return datetime.now(timezone.utc).isoformat()


def evidence_fingerprint(evidence):
    value = copy.deepcopy(evidence)
    value.get('details', {}).pop('matching_pattern_ids', None)
    return digest(value)


def compact(h):
    return {k: copy.deepcopy(h[k]) for k in ('id', 'statement', 'scope', 'lifecycle_status',
        'concept_ids', 'reasoning_codes') if k in h}


class TeacherModelUpdateEngine:
    def __init__(self, folder, *, scope, control=None, policy=None, verify_evidence=None):
        self.folder = writable(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.scope = scope
        self.policy = {**DEFAULT_POLICY, **(policy or {})}
        if any(isinstance(self.policy[k], bool) or not isinstance(self.policy[k], int) or self.policy[k] < 1
            for k in ('max_related_hypotheses', 'max_changed_evidence', 'max_clusters', 'max_cluster_questions', 'max_context_chars')):
            raise ValueError('교사 갱신 문맥/대상 상한은 양의 정수여야 합니다.')
        if self.policy['minimum_sources'] < 2 or self.policy['minimum_questions'] < 2:
            raise ValueError('안전한 승격에는 독립 자료와 문항이 각각 2개 이상 필요합니다.')
        self.control = control or SemanticControl(self.folder / 'decisions')
        self.verify_evidence = verify_evidence
        self._depth = 0
        self._load()

    def _load(self):
        path = self.folder / 'state.json'
        if path.exists():
            value = read_json(path)
            if value.get('state_hash') != digest({k: v for k, v in value.items() if k != 'state_hash'}):
                raise ValueError('교사 상태가 손상됐습니다. 원본 상태를 보존하고 명시적으로 복구하세요.')
            if value['scope'] != self.scope or value['engine_version'] != VERSION:
                raise ValueError('교사 범위/상태 버전이 다릅니다. 명시적 마이그레이션이 필요합니다.')
            if value['policy_hash'] != digest(self.policy):
                raise ValueError('갱신 정책이 바뀌었습니다. 이전 판단을 재해석하지 말고 마이그레이션하세요.')
            self.state = value
        else:
            self.state = {'engine_version': VERSION, 'policy_hash': digest(self.policy),
                'question_versions': [RELATION_VERSION, PREFILTER_VERSION, NOVELTY_VERSION,
                    INTEGRATION_VERSION, SUFFICIENT_VERSION], 'scope': self.scope, 'version': 0,
                'hypotheses': {}, 'evidence': {}, 'relations': {}, 'updates': {},
                'processed': {}, 'clusters': {}, 'pending': {}, 'feedback': {}, 'imported': [], 'prefilters': {}}
        expected = [RELATION_VERSION, PREFILTER_VERSION, NOVELTY_VERSION, INTEGRATION_VERSION, SUFFICIENT_VERSION]
        if self.state['question_versions'] != expected:
            raise ValueError('Jev 질문 버전이 변경됐습니다. 이전 결과를 보존하고 명시적으로 마이그레이션하세요.')

    @contextmanager
    def transaction(self):
        if self._depth:
            yield
            return
        handle = (self.folder / 'writer.lock').open('a+b')
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise ValueError('다른 교사 모델 갱신이 진행 중입니다.') from None
        self._depth = 1
        try:
            self._load()
            self._repair()
            yield
        finally:
            self._depth = 0
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()

    def _repair(self):
        # Additive checkpoint projection: old decisions and question versions stay intact.
        self.state.setdefault('prefilters', {})
        for key, directory in [('hypotheses', 'hypotheses'), ('relations', 'relations'),
            ('updates', 'updates'), ('feedback', 'feedback'), ('pending', 'pending'), ('prefilters', 'prefilters')]:
            for rid, value in self.state[key].items():
                path = self.folder / directory / (rid + '.json')
                try:
                    needs_repair = not path.exists() or read_json(path) != value
                except (ValueError, OSError):
                    needs_repair = True
                if needs_repair:
                    save(path, value)
        for hid, h in self.state['hypotheses'].items():
            if h['lifecycle_status'] == 'candidate':
                save(self.folder / 'candidates' / (hid + '.json'), h)

    def _commit(self):
        self.state['state_hash'] = digest({k: v for k, v in self.state.items() if k != 'state_hash'})
        save(self.folder / 'state.json', self.state)
        self._repair()
        save(self.folder / 'versions' / f"v{self.state['version']}.json", {
            'version': self.state['version'], 'state_hash': self.state['state_hash'],
            'update_ids': list(self.state['updates']), 'hypothesis_ids': list(self.state['hypotheses'])})

    def _change(self, hid, previous, action, evidence_id, decision_id, identity):
        new = self.state['hypotheses'].get(hid)
        if new == previous:
            return
        before = self.state['version']
        self.state['version'] += 1
        record = {'update_id': identity, 'teacher_model_version_before': before,
            'teacher_model_version_after': self.state['version'], 'evidence_id': evidence_id,
            'hypothesis_id': hid, 'jev_decision_id': decision_id, 'action': action,
            'previous_state': previous, 'new_state': copy.deepcopy(new), 'created_at': now()}
        self._validate('teacher_update.schema.json', record)
        self.state['updates'][identity] = record

    @staticmethod
    def _validate(schema, value):
        Draft202012Validator(read_json(Path(__file__).parent / 'schemas' / schema)).validate(value)

    def seed_hypothesis(self, hypothesis, *, lifecycle='candidate', import_id=None):
        with self.transaction():
            hid = hypothesis['id']
            if not hid or not all(c.isalnum() or c in '_-' for c in hid):
                raise ValueError('Invalid hypothesis ID')
            if hid in self.state['hypotheses']:
                return self.state['hypotheses'][hid]
            if lifecycle not in LIFECYCLES:
                raise ValueError('Unknown hypothesis lifecycle')
            context = hypothesis.get('applicable_context', {})
            h = {'id': hid, 'statement': hypothesis['statement'], 'lifecycle_status': lifecycle,
                'scope': {'level': 'insufficient', 'conditions': context.get('conditions', []),
                    'exam_ids': context.get('exam_ids', [])},
                'concept_ids': context.get('concept_ids', []), 'reasoning_codes': context.get('reasoning_codes', []),
                'supporting_evidence': [], 'contradicting_evidence': [], 'weakening_evidence': [],
                'scope_candidates': [], 'statistics': {}, 'legacy': copy.deepcopy(hypothesis),
                'created_at': now(), 'updated_at': now(), 'provenance': import_id or 'nvidia_candidate'}
            self.state['hypotheses'][hid] = h
            self._change(hid, None, 'import_candidate' if import_id else 'create_candidate', None, None,
                         digest(['seed', hid, import_id]))
            self._commit()
            return h

    def register_evidence(self, evidence):
        if not evidence.get('citations'):
            raise ValueError('교사 근거에는 원문 인용이 필요합니다.')
        if self.verify_evidence:
            self.verify_evidence(evidence)
        with self.transaction():
            eid = evidence['id']; fingerprint = evidence_fingerprint(evidence)
            old = self.state['evidence'].get(eid)
            if old and old['fingerprint'] == fingerprint and old['current']:
                return fingerprint
            if old:
                save(self.folder / 'evidence_history' / (old['fingerprint'] + '.json'), old)
            self.state['evidence'][eid] = {'record': copy.deepcopy(evidence),
                'fingerprint': fingerprint, 'current': True}
            save(self.folder / 'evidence' / (fingerprint + '.json'), evidence)
            self._commit()
            return fingerprint

    def reconcile_evidence(self, current):
        """Stale/removed witnesses stop contributing, but old decisions and text survive."""
        with self.transaction():
            changed = False
            for eid, row in self.state['evidence'].items():
                if row['current'] and (eid not in current or row['fingerprint'] != evidence_fingerprint(current[eid])):
                    row['current'] = False; changed = True
            if changed:
                for hid, h in self.state['hypotheses'].items():
                    previous = copy.deepcopy(h)
                    self._statistics(h)
                    if h['lifecycle_status'] == 'active' and not self._minimum(h, 1):
                        h['lifecycle_status'] = 'weak'
                    self._change(hid, previous, 'source_changed_or_removed', None, None,
                        digest(['reconcile', hid, self.state['version'], current]))
                self._commit()

    def relevant_hypotheses(self, evidence):
        details = evidence.get('details', {})
        nodes = details.get('nodes', [])
        concepts = {n['details']['concept_id'] for n in nodes if n['kind'] == 'concept'}
        concepts.update([details['id']] if evidence['kind'] == 'material_concept' else [])
        concepts.update(details[k] for k in ('from', 'to') if k in details)
        codes = {n['details']['code'] for n in nodes if n['kind'] == 'reasoning'}
        rows = [(len(concepts.intersection(h['concept_ids'])) + 2 * len(codes.intersection(h['reasoning_codes'])), h)
            for h in self.state['hypotheses'].values() if h['lifecycle_status'] not in ('retired', 'rejected')]
        # When no semantic keys are available, keep a bounded comparison, not an unrelated verdict.
        rows.sort(key=lambda x: (-x[0], x[1]['id']))
        eligible = [h for rank, h in rows if rank > 0] or [h for _, h in rows]
        return eligible[:self.policy['max_related_hypotheses']], len(eligible)

    def _pending(self, identity, status, evidence_id=None, hypothesis_id=None, decision_id=None):
        self.state['pending'][identity] = {'id': identity, 'status': status, 'evidence_id': evidence_id,
            'hypothesis_id': hypothesis_id, 'decision_id': decision_id, 'created_at': now(), 'resolved': False}

    def _resolved(self, identity):
        if identity in self.state['pending']:
            self.state['pending'][identity]['resolved'] = True

    def prefilter_identity(self, evidence, hypothesis_ids):
        hypotheses = [compact(self.state['hypotheses'][hid]) for hid in sorted(hypothesis_ids)]
        for h in hypotheses:
            h.pop('lifecycle_status', None)
        return digest(['evidence_prefilter', PREFILTER_VERSION, evidence_fingerprint(evidence),
            hypotheses, self.control.threshold_version,
            getattr(self.control.provider, 'model', None) or os.environ.get('JEV_MODEL', 'jev-latest')])

    def generic_evidence_processed(self, evidence, hypothesis_ids):
        if evidence['kind'] == 'question' or any(evidence['id'] in h['contradicting_evidence']
            for h in self.state['hypotheses'].values()):
            return False
        result = self.state.get('prefilters', {}).get(self.prefilter_identity(evidence, hypothesis_ids), {})
        return result.get('status') == 'generic_evidence_preserved'

    def update_related_evidence(self, evidence, hypothesis_ids, *, memory=None, coverage=None):
        """One shared gate before per-H five-question decisions. Never discard a witness."""
        with self.transaction():
            self.register_evidence(evidence)
            identity = self.prefilter_identity(evidence, hypothesis_ids)
            if self.generic_evidence_processed(evidence, hypothesis_ids):
                self._resolved(identity); self._commit()
                return self.state['prefilters'][identity]
            hypotheses = [compact(self.state['hypotheses'][hid]) for hid in hypothesis_ids]
            decision = self.control.judge('teacher_prefilter', {
                'evidence': [evidence], 'existing_hypotheses': hypotheses,
                'related_memory': memory or {}, 'retrieval_coverage': coverage or {}},
                prefilter_questions(1), PREFILTER_VERSION, hypothesis_ids=hypothesis_ids)
            a = decision['raw_answers']
            signal = self.control.noul(a.get('teacher_signal'))
            generic = self.control.noul(a.get('generic_subject_knowledge'))
            mandatory = evidence['kind'] == 'question' or any(
                evidence['id'] in h['contradicting_evidence'] for h in self.state['hypotheses'].values())
            result = {'id': identity, 'evidence_id': evidence['id'],
                'evidence_hash': evidence_fingerprint(evidence), 'hypothesis_ids': list(hypothesis_ids),
                'status': 'pending_review', 'decision_id': decision['decision_id'],
                'question_version': PREFILTER_VERSION, 'mandatory': mandatory,
                'coverage': coverage or {}, 'provenance': copy.deepcopy(evidence['citations']), 'created_at': now()}
            # These are independent predicates: an ambiguous generic flag cannot
            # veto a clear teacher signal or drop a mandatory assessment witness.
            trusted = decision['status'] == 'success'
            if trusted and signal is False and generic is True and not mandatory:
                result['status'] = 'generic_evidence_preserved'
                self._resolved(identity)
            elif trusted and (signal is True or mandatory):
                relations = [self.update_evidence(evidence, hid, memory=memory, coverage=coverage)
                    for hid in hypothesis_ids]
                result['relation_ids'] = [r['id'] for r in relations]
                result['status'] = 'applied' if all(r['status'] == 'applied' for r in relations) else 'pending_review'
                if result['status'] == 'applied': self._resolved(identity)
            if result['status'] == 'pending_review':
                self._pending(identity, 'pending_review', evidence['id'], decision_id=decision['decision_id'])
            self._validate('teacher_prefilter.schema.json', result)
            self.state['prefilters'][identity] = result
            self._commit()
            return result

    def update_evidence(self, evidence, hypothesis_id, *, memory=None, coverage=None):
        with self.transaction():
            fingerprint = self.register_evidence(evidence)
            h = self.state['hypotheses'][hypothesis_id]
            identity = digest(['relation', VERSION, RELATION_VERSION, fingerprint, hypothesis_id,
                h['statement'], h['scope'], self.control.threshold_version])
            if identity in self.state['processed']:
                return self.state['processed'][identity]
            state = {'evidence': evidence, 'hypothesis': compact(h),
                'existing_hypotheses': [compact(h)], 'related_memory': memory or {}, 'coverage': coverage or {}}
            decision = self.control.judge('teacher_relation', state, relation_questions(), RELATION_VERSION,
                                         hypothesis_ids=[hypothesis_id])
            a = decision['raw_answers']; relation = self.control.choice(a.get('relation'))
            scope = self.control.choice(a.get('scope')); strength = a.get('strength', {})
            accepted = decision['status'] == 'success' and relation is not None
            if relation not in ('unrelated', 'insufficient'):
                accepted = accepted and scope not in (None, 'insufficient') and strength.get('confidence', 0) >= self.control.config['choice_confidence']
            rid = identity
            record = {'id': rid, 'evidence_id': evidence['id'], 'evidence_hash': fingerprint,
                'hypothesis_id': hypothesis_id, 'relation': relation if accepted else 'insufficient',
                'raw_relation': a.get('relation', {}).get('choice'),
                'strength': strength.get('score'), 'scope': scope,
                'jev_probability': a.get('relation', {}).get('probabilities', {}).get(relation),
                'jev_confidence': a.get('relation', {}).get('confidence'),
                'question_version': RELATION_VERSION, 'question_versions': decision['question_versions'],
                'jev_decision_id': decision['decision_id'], 'created_at': now(),
                'status': 'applied' if accepted and relation != 'insufficient' else 'pending_review',
                'coverage': coverage or {},
                'provenance': copy.deepcopy(evidence['citations'])}
            self._validate('evidence_relation.schema.json', record)
            self.state['relations'][rid] = record
            if record['status'] == 'pending_review':
                self._pending(identity, 'pending_review', evidence['id'], hypothesis_id, decision['decision_id'])
            else:
                previous = copy.deepcopy(h)
                if relation != 'unrelated':
                    if relation in ('narrows_scope', 'broadens_scope'):
                        h['scope_candidates'].append({'scope': scope, 'relation': relation,
                            'evidence_id': evidence['id'], 'relation_id': rid, 'status': 'pending_review'})
                    self._statistics(h)
                    if relation == 'contradicts' and strength['score'] >= self.policy['strong_contradiction']:
                        h['lifecycle_status'] = 'contested'
                    elif relation == 'weakens' and h['lifecycle_status'] == 'active':
                        h['lifecycle_status'] = 'weak'
                    h['updated_at'] = now()
                    self._change(hypothesis_id, previous, relation, evidence['id'], decision['decision_id'], identity)
                self.state['processed'][identity] = record
                self._resolved(identity)
            self._commit()
            return record

    def _statistics(self, h):
        rows = [r for r in self.state['relations'].values() if r['hypothesis_id'] == h['id']
            and r['status'] == 'applied' and r['relation'] not in ('unrelated', 'insufficient')
            and self.state['evidence'].get(r['evidence_id'], {}).get('current')
            and self.state['evidence'][r['evidence_id']]['fingerprint'] == r['evidence_hash']]
        # Question version migrations never cause the same witness to count twice.
        rows = list({r['evidence_id']: r for r in rows}.values())
        if not rows and not h.get('statistics'):
            return  # Unrelated evidence cannot initialize/change an untouched hypothesis.
        supports = [r for r in rows if r['relation'] in ('reinforces', 'broadens_scope', 'narrows_scope')]
        counters = [r for r in rows if r['relation'] == 'contradicts']
        h['supporting_evidence'] = sorted(r['evidence_id'] for r in supports)
        h['contradicting_evidence'] = sorted(r['evidence_id'] for r in counters)
        h['weakening_evidence'] = sorted(r['evidence_id'] for r in rows if r['relation'] == 'weakens')
        evidence = [self.state['evidence'][r['evidence_id']]['record'] for r in supports]
        sources = {c['source_sha256'] for e in evidence for c in e['citations']}
        questions = {e['origin_id'] for e in evidence if e['kind'] == 'question'}
        denominator = len(rows)
        support_weight = sum(r['strength'] / 3 for r in supports)
        counter_weight = sum(r['strength'] / 3 for r in counters)
        h['statistics'] = {'support_count': len(supports), 'counter_count': len(counters),
            'related_count': denominator, 'source_diversity': len(sources), 'independent_questions': len(questions),
            'support_ratio': len(supports)/denominator if denominator else None,
            'contradiction_ratio': len(counters)/denominator if denominator else None,
            'support_weight': support_weight, 'counter_weight': counter_weight,
            'ranking_weight': max(0, support_weight-counter_weight),
            'unresolved_strong_contradiction': any(r['strength'] >= self.policy['strong_contradiction'] for r in counters),
            'meaning': 'current_observed_relations_not_probability'}

    def _minimum(self, h, coverage):
        stats = h['statistics']
        incomplete_retrieval = any(r.get('coverage', {}).get('hypotheses_selected', 0) <
            r.get('coverage', {}).get('hypotheses_available', 0) for r in self.state['relations'].values()
            if r['hypothesis_id'] == h['id'] and r['status'] == 'applied' and r['relation'] != 'unrelated'
            and self.state['evidence'].get(r['evidence_id'], {}).get('current')
            and self.state['evidence'][r['evidence_id']]['fingerprint'] == r['evidence_hash'])
        return stats.get('independent_questions', 0) >= self.policy['minimum_questions'] and \
            stats.get('source_diversity', 0) >= self.policy['minimum_sources'] and \
            not stats.get('unresolved_strong_contradiction', False) and not incomplete_retrieval and coverage >= self.policy['minimum_coverage']

    def stabilize(self, hid, *, coverage=0):
        with self.transaction():
            h = self.state['hypotheses'][hid]
            if h['lifecycle_status'] in ('rejected', 'retired'):
                return False
            self._statistics(h)
            if not self._minimum(h, coverage) or any(c['status'] == 'pending_review' for c in h['scope_candidates']):
                return False
            evidence = [self.state['evidence'][eid]['record'] for eid in
                [*h['supporting_evidence'], *h['contradicting_evidence'], *h['weakening_evidence']]]
            decision = self.control.judge('teacher_sufficient', {'hypothesis': compact(h),
                'evidence': evidence, 'statistics': h['statistics'], 'coverage': coverage},
                sufficient_questions(), SUFFICIENT_VERSION, hypothesis_ids=[hid])
            if self.control.noul(decision['raw_answers'].get('sufficient')) is not True:
                self._pending(digest(['sufficient', hid, evidence]), 'pending_review', hypothesis_id=hid,
                    decision_id=decision['decision_id']); self._commit(); return False
            previous = copy.deepcopy(h)
            if h['lifecycle_status'] != 'active':
                h['lifecycle_status'] = 'active'; h['updated_at'] = now()
                self._change(hid, previous, 'provisionally_stable', None, decision['decision_id'],
                    digest(['stable', hid, decision['decision_id']]))
                self._commit()
            return True

    def process_cluster(self, cluster, generate_candidate, *, memory=None):
        with self.transaction():
            evidence = cluster['evidence']
            for e in evidence:
                self.register_evidence(e)
            candidates = {}
            available = 0
            for e in evidence:
                rows, total = self.relevant_hypotheses(e); available = max(available, total)
                candidates.update((h['id'], compact(h)) for h in rows)
            closest = list(candidates.values())[:self.policy['max_related_hypotheses']]
            available = max(available, len(candidates))
            identity = digest(['cluster', cluster, PREFILTER_VERSION, NOVELTY_VERSION,
                INTEGRATION_VERSION, self.control.threshold_version])
            previous = self.state['clusters'].get(identity)
            if previous and previous['status'] not in ('pending_review', 'candidate_generation_pending', 'integration_pending'):
                return previous
            state = {'cluster': {k: cluster[k] for k in ('id', 'pattern', 'coverage') if k in cluster},
                'evidence': evidence,
                'existing_hypotheses': closest, 'related_memory': memory or {},
                'retrieval_coverage': {'available': available, 'selected': len(closest)}}
            filtered = self.control.judge('teacher_prefilter', state, prefilter_questions(len(evidence)), PREFILTER_VERSION)
            a = filtered['raw_answers']
            signal = self.control.noul(a.get('teacher_signal')); generic = self.control.noul(a.get('generic_subject_knowledge'))
            gate = None; candidate = previous.get('candidate') if previous else None
            result = {'id': identity, 'status': 'pending_review', 'prefilter_decision_id': filtered['decision_id'],
                'selected_evidence_ids': [e['id'] for e in evidence], 'available_evidence_count': cluster['coverage']['available'],
                'hypothesis_ids': [h['id'] for h in closest], 'created_at': now()}
            ranking = []
            for i, e in enumerate(evidence):
                relevance, novelty = a.get(f'e{i}_relevance', {}), a.get(f'e{i}_novelty', {})
                trusted = all(v.get('confidence', 0) >= self.control.config['choice_confidence'] for v in (relevance, novelty))
                mandatory = e['kind'] == 'question' or any(e['id'] in h['contradicting_evidence'] for h in self.state['hypotheses'].values())
                ranking.append({'evidence_id': e['id'], 'mandatory': mandatory,
                    'relevance': relevance.get('score'), 'novelty': novelty.get('score'),
                    'priority': (100 if mandatory else 0) + (2*relevance['score']+novelty['score'] if trusted else 0),
                    'status': 'judged' if trusted else 'pending_review'})
            ranking.sort(key=lambda r: (-r['priority'], r['evidence_id']))
            result['context_ranking'] = ranking
            if signal is False and generic is True:
                result['status'] = 'generic_evidence_preserved'
            elif signal is True and all(a.get(k, {}).get('confidence', 0) >= self.control.config['choice_confidence'] for k in ('relevance', 'novelty')):
                gate = self.control.judge('teacher_novelty', state, novelty_questions(closest), NOVELTY_VERSION)
                g = gate['raw_answers']; novel = self.control.noul(g.get('novel_pattern'))
                nearest = self.control.choice(g.get('closest')); slow = self.control.noul(g.get('needs_slow_reasoning'))
                result['novelty_decision_id'] = gate['decision_id']
                can_generate = (novel is True and nearest == 'none') or (slow is True and novel is not False and nearest is not None)
                if novel is False and nearest not in (None, 'insufficient'):
                    result['status'] = 'represented_by_existing'
                elif can_generate and len({e['origin_id'] for e in evidence if e['kind'] == 'question'}) >= 2:
                    if candidate is None:
                        try:
                            # Generator receives one complete bounded bundle; no global model.
                            ranked = copy.deepcopy(cluster)
                            order = {r['evidence_id']: i for i, r in enumerate(ranking)}
                            if 'packet' in ranked:
                                aliases = ranked['aliases']
                                ranked['packet']['evidence_cards'].sort(key=lambda c: order[aliases[c['evidence_id']]])
                            candidate = generate_candidate(ranked, closest, memory or {})
                            if candidate is None:
                                result['status'] = 'candidate_abstained'
                            else:
                                result['candidate'] = candidate
                                # Persist the costly result BEFORE integration, so retries never regenerate it.
                                result['status'] = 'integration_pending'
                                self.state['clusters'][identity] = result; self._commit()
                        except (ValueError, OSError, TimeoutError, TypeError, KeyError):
                            result['status'] = 'candidate_generation_pending'
                    if candidate:
                        result['candidate'] = candidate
                        decision = self.control.judge('teacher_integration', {**state, 'candidate': candidate},
                            integration_questions(closest), INTEGRATION_VERSION,
                            hypothesis_ids=[h['id'] for h in closest])
                        answers = decision['raw_answers']; integration = self.control.choice(answers.get('integration'))
                        related = self.control.choice(answers.get('closest'))
                        sufficient = self.control.noul(answers.get('sufficient'))
                        result.update(integration=integration, integration_decision_id=decision['decision_id'])
                        if integration == 'duplicate_existing' and related in self.state['hypotheses']:
                            result.update(status='duplicate_existing', merged_into=related)
                            # A duplicate claim is not a license to auto-count its proposed evidence.
                            for e in evidence:
                                self.update_evidence(e, related, memory=memory, coverage=cluster['coverage'])
                        elif integration in ('new_independent', 'subtype_of_existing', 'broader_than_existing', 'contradicts_existing') and related not in (None, 'insufficient') and (integration == 'new_independent' or related in self.state['hypotheses']):
                            h = self.seed_hypothesis(candidate)
                            result.update(status='candidate_saved', hypothesis_id=h['id'])
                            for e in evidence:
                                self.update_evidence(e, h['id'], memory=memory, coverage=cluster['coverage'])
                            if integration != 'new_independent':
                                h = self.state['hypotheses'][h['id']]
                                prior = copy.deepcopy(h)
                                h['integration_candidate'] = {'relation': integration, 'related_hypothesis_id': related,
                                    'decision_id': decision['decision_id'], 'status': 'pending_review'}
                                self._change(h['id'], prior, 'integration_candidate', None, decision['decision_id'], digest([identity, 'integration']))
                            elif sufficient is True:
                                cov = cluster['coverage']['selected']/max(1, cluster['coverage']['available'])
                                self.stabilize(h['id'], coverage=cov if len(closest) == available else 0)
                        else:
                            result['status'] = 'integration_pending'
            self.state['clusters'][identity] = result
            if result['status'] in ('pending_review', 'candidate_generation_pending', 'integration_pending'):
                self._pending(identity, result['status'], decision_id=(gate or filtered)['decision_id'])
            else:
                self._resolved(identity)
            self._commit()
            return result

    def record_feedback(self, hid, kind, *, reason, scope=None, evidence_ids=(), event_id=None):
        if kind not in FEEDBACK or not reason.strip():
            raise ValueError('피드백 종류와 이유가 필요합니다.')
        with self.transaction():
            if hid not in self.state['hypotheses'] or not set(evidence_ids).issubset(self.state['evidence']):
                raise ValueError('피드백의 가설/근거가 저장된 상태에 없습니다.')
            if kind == 'human_narrowed_scope' and (not isinstance(scope, dict) or not scope.get('conditions')):
                raise ValueError('범위 수정에는 구체 조건이 필요합니다.')
            identity = event_id or digest([hid, kind, reason, scope, sorted(evidence_ids)])
            if not all(c.isalnum() or c in '_-' for c in identity):
                raise ValueError('Invalid feedback ID')
            row = {'id': identity, 'hypothesis_id': hid, 'kind': kind, 'reason': reason,
                'scope': scope, 'evidence_ids': list(evidence_ids), 'created_at': now(),
                'state_version': self.state['version'], 'decision_ids': sorted({r['jev_decision_id'] for r in
                    self.state['relations'].values() if r['hypothesis_id'] == hid})}
            if identity in self.state['feedback']:
                old = self.state['feedback'][identity]
                if any(old[k] != row[k] for k in ('hypothesis_id', 'kind', 'reason', 'scope', 'evidence_ids')):
                    raise ValueError('같은 피드백 ID로 내용을 덮어쓸 수 없습니다.')
                return old
            self.state['feedback'][identity] = row
            h = self.state['hypotheses'][hid]; prior = copy.deepcopy(h)
            if kind == 'human_rejected': h['lifecycle_status'] = 'rejected'
            elif kind == 'human_narrowed_scope':
                h['scope'] = scope
                for c in h['scope_candidates']: c['status'] = 'human_reviewed'
            elif kind in ('human_confirmed', 'observed_in_exam'):
                h['human_confirmation'] = identity
            elif kind == 'contradicted_by_exam': h['lifecycle_status'] = 'contested'
            h['updated_at'] = now()
            self._change(hid, prior, kind, None, None, digest(['feedback', identity]))
            self._commit()
            return row
