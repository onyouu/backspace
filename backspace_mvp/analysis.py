"""Network construction and exact bounded pattern mining."""
from collections import defaultdict
from itertools import combinations, permutations, product
import json

import networkx as nx

from .model import validate


def concept_key(concept_id):
    return "concept:" + concept_id


def graphs(data):
    material = nx.MultiDiGraph(name="Learning Material Concept Network")
    concepts = {c["id"]: c for c in data["concepts"]}
    for concept in concepts.values():
        material.add_node(concept_key(concept["id"]), kind="concept", label=concept["label"])
    grouped = defaultdict(list)
    for rel in data["material_relations"]:
        grouped[rel["from"], rel["to"], rel["relation"]].extend(rel["evidence"])
    for (a, b, relation), refs in sorted(grouped.items()):
        unique = {json.dumps(r, sort_keys=True, ensure_ascii=False): r for r in refs}
        refs = [unique[k] for k in sorted(unique)]
        material.add_edge(concept_key(a), concept_key(b), key=relation, relation=relation,
                          evidence=refs, evidence_count=len(refs),
                          source_count=len({r["source_id"] for r in refs}),
                          assertions=[{'statement': r.get('statement', ''), 'conditions': r.get('conditions', []),
                                       'review_status': r.get('semantic_review', {}).get('status', 'legacy_unreviewed')}
                                      for r in data['material_relations'] if (r['from'], r['to'], r['relation']) == (a, b, relation)])
    question_graphs = {}
    for q in data["questions"]:
        graph = nx.MultiDiGraph(name=q["id"], intent=q["intent"], exam_id=q["exam_id"])
        for c in q["concept_ids"]:
            graph.add_node(concept_key(c), **material.nodes[concept_key(c)])
        for step in q["steps"]:
            graph.add_node(f"question:{q['id']}:{step['id']}", kind="reasoning",
                           **{k: v for k, v in step.items() if k != 'id'})
        def key(node):
            return concept_key(node) if node in q["concept_ids"] else f"question:{q['id']}:{node}"
        for edge in q["edges"]:
            graph.add_edge(key(edge["from"]), key(edge["to"]), key=edge["relation"],
                           relation=edge["relation"], evidence=edge["evidence"], explanation=edge.get('explanation', ''))
        question_graphs[q["id"]] = graph
    combined = material.copy()
    for qid, graph in question_graphs.items():
        combined.add_nodes_from(graph.nodes(data=True))
        for a, b, k, attrs in graph.edges(keys=True, data=True):
            combined.add_edge(a, b, key=f"{qid}:{k}", **attrs, question_id=qid)
    return material, question_graphs, combined


def canonical_motif(graph):
    """Exact directed, node-code and edge-relation preserving canonical form."""
    best = None
    for order in permutations(graph.nodes):
        indices = {n: i for i, n in enumerate(order)}
        candidate = (tuple(graph.nodes[n]["code"] for n in order),
                     tuple(sorted((indices[a], indices[b], d["relation"])
                                  for a, b, d in graph.edges(data=True))))
        if best is None or candidate < best:
            best = candidate
    return best


def mine(question_graphs, questions, min_support=2, max_path_edges=3, max_motif_nodes=4):
    if min_support < 1 or max_path_edges not in (2, 3) or max_motif_nodes not in (3, 4):
        raise ValueError("Support >= 1; paths 2..3 edges; motifs 3..4 nodes")
    buckets = {kind: defaultdict(set) for kind in ("edges", "paths", "subgraphs")}
    q_by_id = {q["id"]: q for q in questions}
    for qid, original in question_graphs.items():
        reasoning = original.subgraph([n for n, d in original.nodes(data=True) if d["kind"] == "reasoning"])
        for a, b, d in reasoning.edges(data=True):
            buckets["edges"][(reasoning.nodes[a]["code"], d["relation"], reasoning.nodes[b]["code"])].add(qid)
        simple = nx.DiGraph(reasoning)
        for start in simple:
            def walk(path):
                if len(path) > 2:
                    relations = [sorted(reasoning[a][b]) for a, b in zip(path, path[1:])]
                    for labels in product(*relations):
                        key = (tuple(reasoning.nodes[n]["code"] for n in path), tuple(labels))
                        buckets["paths"][key].add(qid)
                if len(path) - 1 < max_path_edges:
                    for nxt in simple.successors(path[-1]):
                        if nxt not in path:
                            walk(path + [nxt])
            walk([start])
        for size in range(3, min(len(reasoning), max_motif_nodes) + 1):
            for nodes in combinations(reasoning.nodes, size):
                sub = reasoning.subgraph(nodes)
                if nx.is_weakly_connected(sub):
                    buckets["subgraphs"][canonical_motif(sub)].add(qid)
    result = {}
    for kind, patterns in buckets.items():
        rows = []
        for pattern, ids in patterns.items():
            ids = sorted(ids)
            exams = defaultdict(int)
            for qid in ids:
                exams[q_by_id[qid]["exam_id"]] += 1
            rows.append({"pattern": pattern, "support": len(ids),
                         "support_ratio": len(ids) / len(questions) if questions else 0,
                         "question_ids": ids, "by_exam": dict(sorted(exams.items())),
                         "is_repeated": len(ids) >= min_support,
                         "evidence": [{"question_id": qid, "references": q_by_id[qid]["evidence"]} for qid in ids]})
        result[kind] = sorted(rows, key=lambda r: (-r["support"], json.dumps(r["pattern"], ensure_ascii=False)))
    return result


def analyze(data, min_support=2, exam_id=None):
    validate(data)
    if exam_id:
        data = {**data, "questions": [q for q in data["questions"] if q["exam_id"] == exam_id]}
        if not data["questions"]:
            raise ValueError(f"No questions for exam: {exam_id}")
    material, question_graphs, combined = graphs(data)
    signature = mine(question_graphs, data["questions"], min_support)
    alignment = []
    for concept in data["concepts"]:
        rels = [r for r in data["material_relations"] if concept["id"] in (r["from"], r["to"])]
        qs = [q for q in data["questions"] if concept["id"] in q["concept_ids"]]
        linked_steps = {q['id']: {e['to'] if e['from'] == concept['id'] else e['from']
                                  for e in q['edges'] if concept['id'] in (e['from'], e['to'])} for q in qs}
        alignment.append({"concept_id": concept["id"], "label": concept["label"],
                          "material_relation_ids": [r["id"] for r in rels],
                          "material_source_ids": sorted({e["source_id"] for r in rels for e in r["evidence"]}),
                          "question_ids": [q["id"] for q in qs],
                          "reasoning_codes": sorted({s["code"] for q in qs for s in q["steps"] if s['id'] in linked_steps[q['id']]})})
    report = {"schema_version": data['schema_version'], "scope": data["scope"], "notes": data["notes"],
              "parameters": {"min_support": min_support, "max_path_edges": 3, "max_motif_nodes": 4,
                             "subgraph_mode": "connected_induced", "support_unit": "distinct_question",
                             "exam_filter": exam_id},
              "counts": {"sources": len(data["sources"]), "concepts": len(data["concepts"]),
                         "questions": len(data["questions"]), "material_edges": material.number_of_edges()},
              "sources": data["sources"], "questions": data["questions"], "signature": signature, "concept_alignment": alignment,
              "graphs": {"learning_material": nx.node_link_data(material),
                         "questions": {k: nx.node_link_data(g) for k, g in question_graphs.items()},
                         "combined": nx.node_link_data(combined)}}
    return report, material, question_graphs
