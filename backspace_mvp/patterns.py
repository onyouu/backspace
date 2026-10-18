"""Milestone v0.3: deterministic, question-local patterns; no model calls or scores."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations, permutations, product
import json
from pathlib import Path

import networkx as nx
from jsonschema import Draft202012Validator

from .model import read_json, validate
from .question_graphs import filename, validate_question_graph


ENGINE_VERSION = 'exact-question-local-1'
KINDS = ('nodes', 'edges', 'paths', 'subgraphs')
MODES = ('reasoning_structure', 'concept_reasoning')


def load_active_graphs(data, folder, exam_id=None):
    """Use the active index only; reject stale/missing exports instead of guessing."""
    validate(data)
    folder = Path(folder)
    index = read_json(folder / 'index.json')
    if index['scope'] != data['scope']:
        raise ValueError('문항 그래프와 dataset의 교사 범위가 다릅니다.')
    questions = {q['id']: q for q in data['questions']}
    current = {qid for qid, q in questions.items() if q.get('analysis_version') == 'grounded-2.3'}
    entries = index['questions']
    ids = [e['question_id'] for e in entries]
    if len(ids) != len(set(ids)) or set(ids) != current:
        raise ValueError('활성 문항 index가 오래됐습니다. export_question_graphs로 갱신하세요.')
    matching = [q for q in questions.values() if exam_id is None or q['exam_id'] == exam_id]
    if exam_id is not None and not matching:
        raise ValueError(f'해당 시험 문항이 없습니다: {exam_id}')
    selected = {q['id'] for q in matching}
    graphs = []
    for entry in sorted(entries, key=lambda e: e['question_id']):
        qid = entry['question_id']
        if qid not in selected:
            continue
        if entry['file'] != filename(qid):
            raise ValueError('문항 index의 파일명이 문항 ID와 다릅니다.')
        graph = validate_question_graph(read_json(folder / filename(qid)), data)
        if (entry['content_hash'] != graph['content_hash'] or entry['revision'] != graph['revision']
                or entry['exam_id'] != graph['exam_id'] or entry['question_number'] != graph['question_number']):
            raise ValueError('문항 index와 그래프 버전이 다릅니다. 다시 내보내세요.')
        graphs.append(graph)
    coverage = {'selected_questions': len(matching), 'included_questions': len(graphs),
                'excluded_questions': [{'question_id': q['id'], 'exam_id': q['exam_id'],
                    'reason': 'legacy_needs_reanalysis'} for q in sorted(matching, key=lambda q: q['id'])
                    if q['id'] not in current],
                'denominator_unit': 'included_distinct_question',
                'exam_filter': exam_id, 'active_index_hash': _digest(index)}
    return graphs, coverage


def _digest(value):
    from .pipeline import digest
    return digest(value)


def _network(graph, mode):
    net = nx.MultiDiGraph()
    for node in graph['nodes']:
        if node['kind'] == 'reasoning':
            signature = {'kind': 'reasoning', 'code': node['details']['code']}
        elif mode == 'concept_reasoning' and node['kind'] == 'concept':
            signature = {'kind': 'concept', 'concept_id': node['details']['concept_id']}
        else:
            continue
        net.add_node(node['id'], signature=signature, record=node)
    for edge in graph['edges']:
        if edge['from'] in net and edge['to'] in net:
            net.add_edge(edge['from'], edge['to'], key=edge['id'], record=edge,
                         relation=edge['relation'])
    return net


def _canonical_subgraph(net):
    """Exact directed multigraph isomorphism, bounded to at most four nodes."""
    best = None
    descriptor = None
    canonical_order = None
    for order in permutations(sorted(net.nodes)):
        positions = {node: i for i, node in enumerate(order)}
        nodes = [net.nodes[node]['signature'] for node in order]
        edges = sorted((positions[a], positions[b], attrs['relation'])
                       for a, b, attrs in net.edges(data=True))
        # The lexical representation orders signatures, not occurrence IDs or free text.
        candidate = (tuple(json.dumps(n, sort_keys=True) for n in nodes), tuple(edges))
        if best is None or candidate < best:
            best = candidate
            canonical_order = order
            descriptor = {'nodes': nodes, 'edges': [
                {'from': a, 'to': b, 'relation': relation} for a, b, relation in edges]}
    return descriptor, canonical_order


def mine_patterns(graphs, coverage, scope, *, min_support=2, max_path_edges=3,
                  max_motif_nodes=4, max_candidates=50000):
    if min_support < 1 or max_path_edges not in (2, 3) or max_motif_nodes not in (3, 4) or max_candidates < 1:
        raise ValueError('min_support ≥ 1, path 2..3 edges, subgraph 3..4 nodes, max_candidates ≥ 1')
    if len({g['question_id'] for g in graphs}) != len(graphs):
        raise ValueError('같은 문항을 중복 집계할 수 없습니다.')
    buckets = {kind: {} for kind in KINDS}
    by_exam = Counter(g['exam_id'] for g in graphs)
    for graph in graphs:
        qid = graph['question_id']
        for mode in MODES:
            net = _network(graph, mode)
            spent = 0

            def tick():
                nonlocal spent
                spent += 1
                if spent > max_candidates:
                    raise ValueError(f'패턴 후보 상한 초과: {qid}, {mode}. 부분 결과는 저장하지 않습니다. '
                                     '문항을 나누거나 --max-candidates를 조정하세요.')

            def add(kind, descriptor, node_ids, edge_ids):
                tick()
                pid = 'pat_' + _digest([ENGINE_VERSION, mode, kind, descriptor])[:24]
                row = buckets[kind].setdefault(pid, {'pattern_id': pid, 'mode': mode, 'kind': kind,
                    'descriptor': descriptor, 'matches': defaultdict(list)})
                # Preserve the descriptor's vertex/edge order for an auditable match.
                node_ids, edge_ids = list(node_ids), list(edge_ids)
                records = [net.nodes[n]['record'] for n in node_ids]
                records += [attrs['record'] for _, _, eid, attrs in net.edges(keys=True, data=True) if eid in edge_ids]
                refs = {_digest(ref): ref for record in records for ref in record['evidence']}
                row['matches'][qid].append({'node_ids': node_ids, 'edge_ids': edge_ids,
                    'evidence': [refs[key] for key in sorted(refs)]})

            for node in sorted(net):
                add('nodes', {'node': net.nodes[node]['signature']}, [node], [])
            for a, b, eid, attrs in sorted(net.edges(keys=True, data=True)):
                add('edges', {'from': net.nodes[a]['signature'], 'relation': attrs['relation'],
                    'to': net.nodes[b]['signature']}, [a, b], [eid])

            def walk(path):
                if len(path) >= 3:
                    options = [sorted(net[a][b].items()) for a, b in zip(path, path[1:])]
                    for chosen in product(*options):
                        add('paths', {'nodes': [net.nodes[n]['signature'] for n in path],
                            'relations': [attrs['relation'] for _, attrs in chosen]},
                            path, [eid for eid, _ in chosen])
                if len(path) - 1 < max_path_edges:
                    for nxt in sorted(net.successors(path[-1])):
                        if nxt not in path:
                            walk(path + [nxt])

            for start in sorted(net):
                walk([start])
            for size in range(3, min(max_motif_nodes, len(net)) + 1):
                for node_ids in combinations(sorted(net), size):
                    tick()  # Disconnected candidates also consume the work budget.
                    sub = net.subgraph(node_ids)
                    if nx.is_weakly_connected(sub):
                        descriptor, order = _canonical_subgraph(sub)
                        add('subgraphs', descriptor, order,
                            sorted(eid for _, _, eid in sub.edges(keys=True)))
    q_by_id = {g['question_id']: g for g in graphs}
    result = {}
    for kind, bucket in buckets.items():
        rows = []
        for row in bucket.values():
            matches = row.pop('matches')
            ids = sorted(matches)
            counts = Counter(q_by_id[qid]['exam_id'] for qid in ids)
            rows.append({**row, 'support': len(ids), 'denominator': len(graphs),
                'support_ratio': len(ids) / len(graphs) if graphs else 0,
                'occurrence_count': sum(len(items) for items in matches.values()),
                'is_repeated': len(ids) >= 2, 'meets_min_support': len(ids) >= min_support,
                'question_ids': ids, 'by_exam': [
                    {'exam_id': eid, 'support': counts[eid], 'denominator': by_exam[eid],
                     'support_ratio': counts[eid] / by_exam[eid]} for eid in sorted(by_exam)],
                'evidence': [{'question_id': qid, 'exam_id': q_by_id[qid]['exam_id'],
                    'question_graph_hash': q_by_id[qid]['content_hash'], 'occurrences': matches[qid]} for qid in ids]})
        result[kind] = sorted(rows, key=lambda row: (-row['support'], row['mode'], row['pattern_id']))
    return {'schema_version': '1.0', 'architecture_version': 'teacher-intelligence-0.1',
            'implementation_milestone': '0.3', 'engine_version': ENGINE_VERSION, 'scope': scope,
            'parameters': {'min_support': min_support, 'max_path_edges': max_path_edges,
                'min_path_edges': 2, 'max_motif_nodes': max_motif_nodes, 'min_motif_nodes': 3,
                'max_candidates_per_question_mode': max_candidates, 'subgraph_mode': 'connected_induced',
                'support_unit': 'distinct_question', 'modes': list(MODES)},
            'coverage': coverage, 'exam_denominators': dict(sorted(by_exam.items())),
            'input_graphs': [{'question_id': g['question_id'], 'exam_id': g['exam_id'],
                'revision': g['revision'], 'content_hash': g['content_hash']} for g in graphs],
            'counts': {'questions': len(graphs), 'patterns': {k: len(v) for k, v in result.items()},
                'repeated_patterns': {k: sum(r['is_repeated'] for r in v) for k, v in result.items()}},
            'patterns': result, 'interpretation_status': 'observed_graph_statistics_only',
            'actual_student_behavior': 'not_observed',
            'notes': ['동형 구조는 같은 과학 내용이나 평가관을 뜻하지 않습니다.',
                'Task/이해 증거/출제 의도 문장은 의미가 같다고 자동 병합하지 않습니다.',
                '반복 통계는 추출된 요구 구조이며 교사의 사적 의도·중요도·학생 행동 점수가 아닙니다.',
                '빈도가 없는 패턴은 출력하지 않으며 singleton도 보존합니다.']}


def build_patterns(state, out=None, graphs_dir=None, exam_id=None, **parameters):
    from .pipeline import save, writable
    state = Path(state).resolve()
    folder = Path(graphs_dir).resolve() if graphs_dir else state.parent / 'question_graphs'
    out = writable(out if out else state.parent / 'patterns.json')
    if (out == state or out == state.parent / 'material_graph.json'
            or folder == out.parent or folder in out.parents):
        raise ValueError('패턴 출력은 dataset/자료 그래프/문항 그래프 파일과 별도로 저장하세요.')
    data = read_json(state)
    graphs, coverage = load_active_graphs(data, folder, exam_id)
    report = mine_patterns(graphs, coverage, data['scope'], **parameters)
    report['dataset_hash'] = _digest(data)
    fingerprint = _digest(report)
    old = read_json(out) if out.exists() else None
    if old and old['scope'] != data['scope']:
        raise ValueError('다른 교사의 패턴 상태를 덮어쓸 수 없습니다.')
    schema = read_json(Path(__file__).parent / 'schemas/patterns.schema.json')
    if old and old['content_hash'] == fingerprint:
        Draft202012Validator(schema).validate(old)
        if {k: old[k] for k in report} != report:
            raise ValueError('패턴 상태의 내용과 해시가 다릅니다.')
        return old
    value = {**report, 'content_hash': fingerprint, 'revision': old['revision'] + 1 if old else 1,
             'previous_hash': old['content_hash'] if old else None, 'updated_at': datetime.now(timezone.utc).isoformat()}
    Draft202012Validator(schema).validate(value)
    if old:
        save(out.parent / 'pattern_history' / f"{out.stem}-r{old['revision']}-{_digest(old)[:16]}.json", old)
    save(out, value)
    return value
