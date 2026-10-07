"""Schema and cross-reference validation; no extraction guesses here."""
import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).parent / "schemas" / "dataset.schema.json"
REPORT_SCHEMA = SCHEMA.with_name("analysis.schema.json")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def index_unique(items, name):
    result = {}
    for item in items:
        if item["id"] in result:
            raise ValueError(f"Duplicate {name} ID: {item['id']}")
        result[item["id"]] = item
    return result


def validate(data):
    Draft202012Validator(read_json(SCHEMA)).validate(data)
    sources = index_unique(data["sources"], "source")
    concepts = index_unique(data["concepts"], "concept")
    codes = index_unique(data["reasoning_codes"], "reasoning code")
    questions = index_unique(data["questions"], "question")
    index_unique(data["material_relations"], "material relation")

    def evidence(refs, allowed_kind=None):
        for ref in refs:
            if ref["source_id"] not in sources:
                raise ValueError(f"Unknown evidence source: {ref['source_id']}")
            source = sources[ref["source_id"]]
            if allowed_kind and source["kind"] != allowed_kind:
                raise ValueError(f"Expected {allowed_kind} evidence: {ref['source_id']}")
            excerpts = {p["locator"]: p["text"] for p in source["excerpts"]}
            if ref["locator"] not in excerpts:
                raise ValueError(f"Unknown evidence location: {ref}")
            if ref["quote"] not in excerpts[ref["locator"]]:
                raise ValueError(f"Quote absent from stored excerpt: {ref}")

    for source in sources.values():
        locators = [p["locator"] for p in source["excerpts"]]
        if len(locators) != len(set(locators)):
            raise ValueError(f"Duplicate excerpt location: {source['id']}")
        projection=source.get('graph_projection')
        if projection:
            skipped=projection['skipped_units']
            if (source['kind']!='learning_material'
                or projection['projected_notes']+projection['notes_only']!=projection['total_notes']
                or projection['notes_only']!=len(skipped)
                or len({u.get('note_id') for u in skipped})!=len(skipped)):
                raise ValueError('Graph projection coverage/counts disagree')
            for unit in skipped:
                text=next((p['text'] for p in source['excerpts'] if p['locator']==unit.get('locator')),None)
                span=unit.get('source_span',{})
                if text is None or not 0<=span.get('start',-1)<span.get('end',-1)<=len(text):
                    raise ValueError('Skipped graph unit is outside source text')
        for locator, report in source.get('visual_context', {}).items():
            from .visual import validate_result
            from .pipeline import digest
            if (report['source_sha256'] != source['sha256'] or report['locator'] != locator or
                    report['content_hash'] != digest({k:v for k,v in report.items() if k != 'content_hash'})):
                raise ValueError('Visual context provenance mismatch')
            validate_result(report['result'], report['images'])
        for block in source.get('perception',{}).get('blocks',[]):
            text=next((p['text'] for p in source['excerpts'] if p['locator']==block['locator']),None)
            if text is None or not 0<=block['start']<block['end']<=len(text):
                raise ValueError('Transcription provenance is outside accepted text')
            if block['status'] not in ('accepted','human_verified'):
                raise ValueError('Unreviewed transcription cannot support a graph')
    for rel in data["material_relations"]:
        if rel["from"] not in concepts or rel["to"] not in concepts:
            raise ValueError(f"Unknown material concept: {rel['id']}")
        evidence(rel["evidence"], "learning_material")
        if rel.get('visual_context_hash'):
            if not any(sources[e['source_id']].get('visual_context',{}).get(e['locator'],{}).get('content_hash') == rel['visual_context_hash'] for e in rel['evidence']):
                raise ValueError('Visual relation has no matching page evidence')
    from .materials import emphasis_is_explicit
    observations = data.get('material_observations', [])
    index_unique(observations, 'material observation')
    observed_pages = set()
    for observation in observations:
        if observation['concept_id'] not in concepts:
            raise ValueError('Unknown observed material concept')
        evidence(observation['evidence'], 'learning_material')
        evidence(observation['explicit_emphasis'], 'learning_material')
        ref = observation['evidence'][0]
        key = (ref['source_id'], ref['locator'], observation['concept_id'])
        if key in observed_pages:
            raise ValueError('Duplicate material concept on one source/page')
        observed_pages.add(key)
        if observation['surface_form'] not in ref['quote']:
            raise ValueError('Material concept surface form is absent from quote')
        from .staged import normalize
        concept = concepts[observation['concept_id']]
        if normalize(observation['surface_form']) not in {normalize(s) for s in [concept['label'], *concept['aliases']]}:
            raise ValueError('Material concept is not a registered surface form')
        from .pipeline import digest
        if observation['id'] != 'mo_' + digest(list(key))[:20]:
            raise ValueError('Material observation identity mismatch')
        for emphasis in observation['explicit_emphasis']:
            if (emphasis['source_id'], emphasis['locator']) != key[:2]:
                raise ValueError('Material emphasis is outside its source/page')
            if not emphasis_is_explicit(emphasis['quote'], observation['surface_form']):
                raise ValueError('Material emphasis has no explicit marker or concept')
    for q in questions.values():
        if not set(q["concept_ids"]) <= concepts.keys():
            raise ValueError(f"Unknown question concept: {q['id']}")
        evidence(q["evidence"], "exam")
        evidence(q["intent"]["evidence"], "exam")
        q_sources = {r["source_id"] for r in q["evidence"]}
        if any(sources[s]["exam_id"] != q["exam_id"] for s in q_sources):
            raise ValueError(f"Question and source exam IDs disagree: {q['id']}")
        steps = index_unique(q["steps"], "step")
        if set(steps) & set(q["concept_ids"]):
            raise ValueError(f"Step and concept IDs overlap: {q['id']}")
        for step in steps.values():
            if step["code"] not in codes:
                raise ValueError(f"Unknown reasoning code: {step['code']}")
            if 'evidence' in step:
                evidence(step['evidence'], 'exam')
        endpoints = set(steps) | set(q["concept_ids"])
        seen = set()
        for edge in q["edges"]:
            if edge["from"] not in endpoints or edge["to"] not in endpoints:
                raise ValueError(f"Unknown question edge endpoint: {q['id']}")
            key = (edge["from"], edge["to"], edge["relation"])
            if key in seen:
                raise ValueError(f"Duplicate question edge: {q['id']} {key}")
            seen.add(key)
            if edge["from"] == edge["to"]:
                raise ValueError(f"Self edge: {q['id']}")
            evidence(edge["evidence"], "exam")
            if not {r["source_id"] for r in edge["evidence"]} <= q_sources:
                raise ValueError(f"Edge evidence is outside this question: {q['id']}")
            if any(not any(r['quote'] in local['quote'] for local in q['evidence']
                           if r['source_id'] == local['source_id'] and r['locator'] == local['locator'])
                   for r in edge['evidence']):
                raise ValueError(f"Edge quote is outside this question span: {q['id']}")
        if not {r["source_id"] for r in q["intent"]["evidence"]} <= q_sources:
            raise ValueError(f"Intent evidence is outside this question: {q['id']}")
        for concept in q["concept_ids"]:
            if not any(e["from"] == concept or e["to"] == concept for e in q["edges"]):
                raise ValueError(f"Unlinked question concept: {q['id']} {concept}")
        for step in steps:
            if not any(e["from"] == step or e["to"] == step for e in q["edges"]):
                raise ValueError(f"Unlinked reasoning step: {q['id']} {step}")
        if 'analysis_version' in q:
            validate_grounded_question(q, sources, steps)
    return data


def merge(base, addition):
    """Append by stable ID; replay is idempotent; conflicts require explicit editing."""
    validate(base)
    validate(addition)
    if base["scope"] != addition["scope"]:
        raise ValueError("Cannot merge different teacher/subject scopes")
    merged = copy.deepcopy(base)
    if addition['schema_version'] == '1.1':
        merged['schema_version'] = '1.1'
    for key in ("sources", "concepts", "reasoning_codes", "material_relations", "questions"):
        existing = index_unique(merged[key], key)
        for item in addition[key]:
            if item["id"] in existing and existing[item["id"]] != item:
                previous = existing[item["id"]]
                if key == "sources" and {k: v for k, v in previous.items() if k != "excerpts"} == {k: v for k, v in item.items() if k != "excerpts"}:
                    excerpts = {e["locator"]: e for e in previous["excerpts"]}
                    for excerpt in item["excerpts"]:
                        if excerpt["locator"] in excerpts and excerpts[excerpt["locator"]] != excerpt:
                            raise ValueError(f"Conflicting excerpt: {item['id']} {excerpt['locator']}")
                        if excerpt["locator"] not in excerpts:
                            previous["excerpts"].append(copy.deepcopy(excerpt))
                            excerpts[excerpt["locator"]] = excerpt
                else:
                    raise ValueError(f"Conflicting {key} ID: {item['id']}; edit the dataset explicitly")
            if item["id"] not in existing:
                merged[key].append(copy.deepcopy(item))
                existing[item["id"]] = item
    if 'material_observations' in addition:
        existing = index_unique(merged.setdefault('material_observations', []), 'material observation')
        for item in addition['material_observations']:
            if item['id'] in existing and existing[item['id']] != item:
                raise ValueError('Conflicting material observation; use --refresh')
            if item['id'] not in existing:
                merged['material_observations'].append(copy.deepcopy(item))
                existing[item['id']] = item
    return validate(merged)


def validate_grounded_question(q, sources, steps):
    from .pipeline import digest
    claims = index_unique(q['claims'], 'claim')
    retrieval = q['retrieval']
    blocks = retrieval['selected_blocks']
    answer_blocks = []
    if q['analysis_version'] == 'grounded-2.3':
        context = q['answer_key_context']
        answer_blocks = context['blocks']
        if context['status'] != ('provided' if answer_blocks else 'not_provided'):
            raise ValueError('Answer-key availability mismatch')
        if len({b['block_id'] for b in answer_blocks}) != len(answer_blocks) or sum(len(b['text']) for b in answer_blocks) > 6000:
            raise ValueError('Answer-key duplicate or budget mismatch')
        primary = q['evidence'][0]
        if q['id'] != primary['source_id'] + ':q:' + digest([primary['locator'], q['title']])[:16] or q['prompt_excerpt'] != primary['quote']:
            raise ValueError('Question identity differs from its source span')
        if context['exam_locator'] != primary['locator']:
            raise ValueError('Answer-key question locator mismatch')
        expected = next((m['block_ids'] for m in sources[primary['source_id']].get('answer_key_mapping', [])
                         if m['exam_locator'] == primary['locator'] and m['question_number'] == q['title']), [])
        if expected != [b['block_id'] for b in answer_blocks]:
            raise ValueError('Answer-key blocks belong to a different question mapping')
        for block in answer_blocks:
            source = sources.get(block['source_id'])
            if not source or source['kind'] != 'answer_key' or source['exam_id'] != q['exam_id'] or source['sha256'] != block['source_sha256']:
                raise ValueError('Answer-key source identity mismatch')
            text = next((e['text'] for e in source['excerpts'] if e['locator'] == block['locator']), None)
            if text is None or not (0 <= block['start'] < block['end'] <= len(text)) or text[block['start']:block['end']] != block['text']:
                raise ValueError('Answer-key text is not the original substring')
            if block['block_id'] != 'ak_' + digest([source['sha256'], source['id'], block['locator'], block['start'], block['end']])[:20]:
                raise ValueError('Answer-key block identity mismatch')
    if len({b['block_id'] for b in blocks}) != len(blocks):
        raise ValueError('Duplicate retrieved block')
    for block in blocks:
        source = sources.get(block['source_id'])
        if not source or source['kind'] != 'learning_material' or source['sha256'] != block['source_sha256']:
            raise ValueError('Retrieved source identity mismatch')
        excerpts = {e['locator']: e['text'] for e in source['excerpts']}
        text = excerpts.get(block['locator'])
        if text is None or not (0 <= block['start'] < block['end'] <= len(text)):
            raise ValueError('Retrieved block offset mismatch')
        if text[block['start']:block['end']] != block['text']:
            raise ValueError('Retrieved text is not the original substring')
        if block['block_id'] != 'b_' + digest([source['sha256'], source['id'], block['locator'], block['start'], block['end']])[:20]:
            raise ValueError('Retrieved block identity mismatch')
    if retrieval['context_chars'] != sum(len(b['text']) for b in blocks) or retrieval['context_chars'] > retrieval['max_chars']:
        raise ValueError('Retrieval budget mismatch')
    if len(blocks) > retrieval['top_k'] or len(blocks) > retrieval['matched_blocks'] or retrieval['matched_blocks'] > retrieval['total_blocks']:
        raise ValueError('Retrieval count mismatch')
    for claim in claims.values():
        if claim['review_status'] == 'supported' and not claim['evidence']:
            raise ValueError('An uncited claim cannot be source-supported')
        for ref in claim['evidence']:
            source = sources.get(ref['source_id'])
            if not source:
                raise ValueError('Unknown claim evidence source')
            if source['kind'] == 'exam':
                allowed = q['evidence']
                valid = any(ref['source_id'] == e['source_id'] and ref['locator'] == e['locator'] and ref['quote'] in e['quote'] for e in allowed)
            else:
                valid = any(ref['source_id'] == b['source_id'] and ref['locator'] == b['locator'] and ref['quote'] in b['text'] for b in [*blocks, *answer_blocks])
            if not valid:
                raise ValueError('Claim evidence is outside the retrieved/question context')
    for step in steps.values():
        if not set(step['claim_ids']) <= claims.keys():
            raise ValueError('Unknown step claim reference')
        for ref in step['evidence']:
            if not any(ref['source_id'] == e['source_id'] and ref['locator'] == e['locator'] and ref['quote'] in e['quote'] for e in q['evidence']):
                raise ValueError('Step evidence is outside this question span')
        if q['analysis_version'] == 'grounded-2.3':
            for ref in step['assessment_evidence']:
                valid = any(ref['source_id'] == e['source_id'] and ref['locator'] == e['locator'] and ref['quote'] in e['quote'] for e in q['evidence'])
                valid = valid or any(ref['source_id'] == b['source_id'] and ref['locator'] == b['locator'] and ref['quote'] in b['text'] for b in [*blocks, *answer_blocks])
                if not valid:
                    raise ValueError('Assessment evidence is outside the question context')
    if q['analysis_version'] == 'grounded-2.3':
        for ref in q['task']['evidence']:
            if not any(ref['source_id'] == e['source_id'] and ref['locator'] == e['locator'] and ref['quote'] in e['quote'] for e in q['evidence']):
                raise ValueError('Task evidence is outside this question')
        connections = {(row['concept_id'], row['step_id']) for row in q['concept_confidences']}
        expected = {(e['to'], e['from']) for e in q['edges'] if e['to'] in q['concept_ids'] and e['from'] in steps}
        if connections != expected or len(connections) != len(q['concept_confidences']):
            raise ValueError('Concept confidence references do not match question connections')
    needs_review = any(c['review_status'] != 'supported' for c in claims.values())
    if q['analysis_status'] != ('needs_reference_review' if needs_review else 'ai_reviewed'):
        raise ValueError('Analysis status does not match claim review status')
    final = q['review_history'][-1]['review']
    if q['analysis_version'] == 'grounded-2.3' and (len(final['task_verdicts']) != 1 or final['task_verdicts'][0]['index'] != 0 or final['task_verdicts'][0]['status'] != 'supported'):
        raise ValueError('Unresolved task review')
    for key, count in [('claim_verdicts', len(claims)), ('step_verdicts', len(steps))]:
        if len(final[key]) != count or {v['index'] for v in final[key]} != set(range(count)):
            raise ValueError('Incomplete semantic review')
    if final['missing_requirements'] or final['issues'] or any(v['status'] != 'supported' for v in final['step_verdicts'] + final['link_verdicts']):
        raise ValueError('Unresolved semantic review')
    for i, claim in enumerate(q['claims']):
        verdict = next(v for v in final['claim_verdicts'] if v['index'] == i)
        if verdict['status'] != claim['review_status']:
            raise ValueError('Claim status differs from semantic review')
    if q['analysis_version'] in ('grounded-2.2', 'grounded-2.3'):
        grounding = q['review_history'][-1]['grounding_verdicts']
        if len(grounding) != len(claims) or {v['index'] for v in grounding} != set(range(len(claims))):
            raise ValueError('Incomplete claim grounding review')
        for verdict in grounding:
            if verdict['status'] != 'supported' and q['claims'][verdict['index']]['review_status'] == 'supported':
                raise ValueError('Grounding failure cannot be promoted to supported')
        if any(c['review_status'] != 'supported' and c['evidence'] for c in q['claims']):
            raise ValueError('Unproven claims cannot retain supporting citations')
        audits = [c for c in q['claims'] if c['origin'] == 'step_output']
        if len(audits) != len(steps) or {c['step_id'] for c in audits} != set(steps):
            raise ValueError('Every step output needs its own grounding audit')
        for claim in audits:
            step = steps[claim['step_id']]
            if claim['statement'] != step['output'] or claim['conditions'] != step['conditions'] or claim['id'] not in step['claim_ids']:
                raise ValueError('Step output differs from its audited claim')
            if q['analysis_version'] == 'grounded-2.3' and claim['confidence'] != step['confidence']:
                raise ValueError('Step output confidence differs from its application-owned audit')


def validate_report(report):
    # JSON serialization turns internal tuple keys into the schema's arrays.
    normalized = json.loads(json.dumps(report, ensure_ascii=False))
    Draft202012Validator(read_json(REPORT_SCHEMA)).validate(normalized)
    total = normalized["counts"]["questions"]
    ids = {q["id"] for q in normalized["questions"]}
    if len(ids) != total:
        raise ValueError("Report question count disagrees with question IDs")
    for rows in normalized["signature"].values():
        for row in rows:
            if row["support"] != len(row["question_ids"]) or not set(row["question_ids"]) <= ids:
                raise ValueError("Pattern support disagrees with distinct question references")
            if row["support_ratio"] != row["support"] / total:
                raise ValueError("Pattern support ratio disagrees with question count")
            if sum(row["by_exam"].values()) != row["support"]:
                raise ValueError("Exam counts disagree with pattern support")
    return normalized
