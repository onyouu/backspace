"""Architecture milestone v0.1: auditable cumulative material graph, no salience scoring."""
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator


EMPHASIS_MARKERS = ('중요', '핵심', '반드시', '주의', '강조', '기억')


def emphasis_is_explicit(quote, surface):
    # Text markers only. Typography, colour and implied importance are not observations.
    return surface in quote and any(word in quote for word in EMPHASIS_MARKERS)


def source_type(source):
    return source.get('material_type') or ('ppt' if source['format'] == 'pptx' else 'unspecified')


def projection(data):
    """Recompute from accepted evidence. Never increment counters on ingestion/replay."""
    from .pipeline import digest
    sources = {s['id']: s for s in data['sources'] if s['kind'] == 'learning_material'}
    registry = {c['id']: c for c in data['concepts']}
    observations = data.get('material_observations', [])
    node_refs, emphasis, node_confidence = defaultdict(list), defaultdict(list), defaultdict(list)
    grouped = defaultdict(list)

    def citation(ref, confidence, basis):
        from .perception import transcription_refs
        source = sources[ref['source_id']]
        text = next(p['text'] for p in source['excerpts'] if p['locator'] == ref['locator'])
        # Explicitly choose the first identical span; source/page, not literal count, is our unit.
        start = text.index(ref['quote'])
        page = re.fullmatch(r'(?:p|slide)(\d+)', ref['locator'])
        return {'source': source['id'], 'source_title': source['title'], 'source_sha256': source['sha256'],
                'page': int(page[1]) if page else None, 'locator': ref['locator'], 'question_id': None,
                'raw_evidence': ref['quote'], 'char_start': start, 'char_end': start + len(ref['quote']),
                'offset_policy': 'first_exact_match', 'confidence': confidence, 'confidence_basis': basis,
                'transcription':transcription_refs(source,ref['locator'],start,start+len(ref['quote']))}

    for row in observations:
        cid = row['concept_id']
        node_refs[cid].extend(citation(e, row['confidence'], 'llm_self_report') for e in row['evidence'])
        emphasis[cid].extend(citation(e, row['confidence'], 'llm_self_report') for e in row['explicit_emphasis'])
        node_confidence[cid].append({'observation_id': row['id'], 'value': row['confidence']})
    for row in data['material_relations']:
        grouped[(row['from'], row['to'], row['relation'])].append(row)
        # Legacy relation endpoints are retained, visibly without audited concept observations.
        for cid in (row['from'], row['to']):
            for ref in row['evidence']:
                if not any(c['source'] == ref['source_id'] and c['locator'] == ref['locator'] for c in node_refs[cid]):
                    node_refs[cid].append(citation(ref, None, 'legacy_relation_endpoint'))

    def stats(refs):
        pages = sorted({(r['source'], r['locator']) for r in refs})
        ids = sorted({r['source'] for r in refs})
        return {'frequency': len(pages), 'source_count': len(ids),
                'source_types': sorted({source_type(sources[s]) for s in ids}),
                'source_formats': sorted({sources[s]['format'] for s in ids}),
                'pages': [{'source': s, 'locator': p} for s, p in pages]}

    def unique(refs):
        return [value for _, value in sorted({digest(r): r for r in refs}.items())]

    nodes = []
    for cid in sorted(node_refs):
        refs = unique(node_refs[cid])
        markers = unique(emphasis[cid])
        legacy = any(r['confidence_basis'] == 'legacy_relation_endpoint' for r in refs)
        nodes.append({**registry[cid], **stats(refs), 'evidence': refs,
                      'extraction_confidences': sorted(node_confidence[cid], key=lambda c: c['observation_id']),
                      'observation_status': 'legacy_needs_reextraction' if legacy else 'source_linked',
                      'explicit_emphasis': {'status': 'observed' if markers else ('legacy_unknown' if legacy else 'not_observed'),
                                            'frequency': len({(r['source'], r['locator']) for r in markers}), 'evidence': markers}})
    edges = []
    for key, rows in sorted(grouped.items()):
        refs, assertions = [], []
        for row in sorted(rows, key=lambda r: r['id']):
            evidence = [citation(e, row.get('confidence'), 'llm_self_report' if 'confidence' in row else 'legacy_unknown')
                        for e in row['evidence']]
            refs.extend(evidence)
            assertions.append({'id': row['id'], 'statement': row.get('statement'), 'conditions': row.get('conditions', []),
                               'confidence': row.get('confidence'), 'semantic_review': row.get('semantic_review'),
                               'evidence': evidence,
                               **({'visual_context_hash':row['visual_context_hash']} if row.get('visual_context_hash') else {})})
        refs = unique(refs)
        edges.append({'id': 'me_' + digest(list(key))[:20], 'from': key[0], 'to': key[1], 'relation': key[2],
                      **stats(refs), 'assertions': assertions, 'evidence': refs})
    source_metadata = [{k: s[k] for k in ('id', 'title', 'path', 'sha256', 'format', 'material_type', 'material_analysis_version', 'visual_context', 'graph_projection') if k in s}
                       for _, s in sorted(sources.items())]
    return {'schema_version': '1.0', 'architecture_version': 'teacher-intelligence-0.1',
            'implementation_milestone': '0.1', 'scope': data['scope'],
            'frequency_unit': 'distinct_source_page', 'confidence_meaning': 'extraction_self_report_not_teacher_importance',
            'sources': source_metadata, 'concepts': nodes, 'relations': edges,
            'needs_reextraction': sorted(s['id'] for s in sources.values()
                                        if s.get('material_analysis_version') != 'teacher-material-1.0')}


def validate_material_graph(graph, data):
    from .model import read_json, validate
    from .pipeline import digest
    validate(data)
    schema = Path(__file__).parent / 'schemas/material_graph.schema.json'
    Draft202012Validator(read_json(schema)).validate(graph)
    expected = projection(data)
    actual = {k: graph[k] for k in expected}
    if actual != expected or graph['content_hash'] != digest(expected):
        raise ValueError('자료 그래프의 빈도·근거·내용 해시가 원본 dataset과 다릅니다.')
    return graph


def export_material_graph(data, out):
    from .model import read_json, validate
    from .pipeline import digest, save, writable
    out = writable(out)
    validate(data)
    projected = projection(data)
    fingerprint = digest(projected)
    old = read_json(out) if out.exists() else None
    if old:
        schema = Path(__file__).parent / 'schemas/material_graph.schema.json'
        Draft202012Validator(read_json(schema)).validate(old)
        if old['scope'] != projected['scope']:
            raise ValueError('다른 교사 범위의 자료 그래프를 덮어쓸 수 없습니다.')
        if old['content_hash'] == fingerprint:
            return validate_material_graph(old, data)
    graph = {**projected, 'content_hash': fingerprint, 'revision': old['revision'] + 1 if old else 1,
             'previous_hash': old['content_hash'] if old else None,
             'updated_at': datetime.now(timezone.utc).isoformat()}
    validate_material_graph(graph, data)
    if old:
        save(out.parent / 'material_graph_history' / f"r{old['revision']}-{old['content_hash'][:16]}.json", old)
    save(out, graph)
    return graph
