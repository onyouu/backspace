"""Read-only portable views. Canonical artifacts are never rewritten by export."""
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from .model import read_json
from .pipeline import digest

EXPORT_VERSION = 'backspace-export-1'
FILENAMES = {'model': 'teacher_model.runtime.json', 'evidence': 'teacher_model.evidence.json',
             'recognition': 'backspace-recognition.zip', 'backup': 'backspace-full-backup.zip'}


def pick(value, keys):
    return {key: value[key] for key in keys if key in value}


def portable_model(model, graph=None):
    """One runtime model, plus deduplicated witnesses addressable by stable IDs."""
    citations = {}
    sources = {s['id']: pick(s, ('id', 'title', 'sha256', 'kind', 'format', 'page_count'))
               for s in model.get('material_sources', [])}

    def refs(items):
        ids = []
        for r in items:
            source = r.get('source', r.get('source_id'))
            c = {'source_id': source, 'locator': r.get('locator'),
                 'quote': r.get('raw_evidence', r.get('quote', '')),
                 'start': r.get('char_start', r.get('start_offset')),
                 'end': r.get('char_end', r.get('end_offset'))}
            # Keep source identity in the catalog, not in every citation.
            if source not in sources:
                sources[source] = {'id': source, 'title': r.get('source_title'),
                                   'sha256': r.get('source_sha256')}
            cid = 'ref_' + digest(c)[:24]
            citations[cid] = c
            if cid not in ids:
                ids.append(cid)
        return ids

    observations = {}
    for e in model.get('evidence_registry', []):
        observations[e['id']] = {**pick(e, ('kind', 'origin_id', 'details')),
                                'citation_ids': refs(e.get('citations', []))}
    hypotheses = []
    for h in model.get('assessment_ideals', []):
        item = pick(h, ('id', 'statement', 'dimension', 'reasoning_chain', 'status', 'readiness',
                       'lifecycle_status', 'applicable_context', 'counter_evidence_status',
                       'alternative_explanations', 'limitations', 'next_validation_data'))
        for field in ('supporting_evidence', 'counter_evidence'):
            item[field + '_ids'] = [r['evidence_id'] for r in h.get(field, [])]
        hypotheses.append(item)
    assertions = []
    for r in model.get('material_relations', []):
        assertions.append({**pick(r, ('id', 'from', 'to', 'relation', 'statement', 'conditions')),
                           'review_status': r.get('semantic_review', {}).get('status'),
                           'citation_ids': refs(r.get('evidence', []))})
    concepts = [pick(c, ('concept_id', 'label', 'aliases', 'teacher_importance', 'status'))
                for c in model.get('concept_importance', [])]
    concept_refs = {}
    for c in (graph or {}).get('concepts', []):
        concept_refs[c['id']] = refs(c.get('evidence', []))
    edges = [{**pick(r, ('id', 'from', 'to', 'relation')),
              'assertion_ids': [a['id'] for a in r.get('assertions', [])]}
             for r in (graph or {}).get('relations', [])]
    identity = {'export_version': EXPORT_VERSION, 'model_hash': model['content_hash'],
                'model_revision': model.get('revision'), 'scope': model.get('scope')}
    evidence = {**identity, 'kind': 'evidence', 'sources': list(sources.values()),
                'citations': citations, 'observations': observations, 'concept_citation_ids': concept_refs}
    runtime = {**identity, 'kind': 'runtime', 'status': model.get('status'),
               'concepts': concepts, 'relations': edges, 'assertions': assertions,
               'hypotheses': hypotheses, 'dominant_reasoning': model.get('dominant_reasoning'),
               'evidence_file': FILENAMES['evidence'], 'evidence_hash': digest(evidence),
               'usage': 'Conditional predictions, not model weights or measured accuracy. '
                        'Resolve citation_ids and evidence IDs in the matching evidence file. '
                        'Retrieve only task-relevant entries for inference; preserve conditions and counterevidence.'}
    runtime['export_hash'] = digest(runtime)
    return runtime, evidence


def validate_export(base, kind):
    if kind not in FILENAMES:
        raise ValueError('지원하지 않는 다운로드입니다.')
    if not (Path(base) / 'teacher/teacher_model.json').is_file():
        raise ValueError('저장된 모델이 없습니다.')


def json_export(base, kind):
    validate_export(base, kind)
    root = Path(base) / 'teacher'
    graph = read_json(root / 'material_graph.json') if (root / 'material_graph.json').exists() else None
    runtime, evidence = portable_model(read_json(root / 'teacher_model.json'), graph)
    return runtime if kind == 'model' else evidence


def archive_export(base, kind):
    """Disk-backed ZIP, with a per-file checksum manifest; no project/auth files."""
    validate_export(base, kind)
    if kind not in ('backup', 'recognition'):
        raise ValueError('압축 다운로드 종류가 다릅니다.')
    base = Path(base).resolve()
    # Deliberately no project-root traversal (.env, login storage, code, logs).
    roots = ('files.json', 'uploads', 'perception', 'removed_sources', 'teacher', 'scope',
             'current_plan.json', 'plan_history', 'plan_checkpoints') if kind == 'backup' else ('files.json', 'perception')
    paths = []
    for name in roots:
        root = base / name
        if root.is_symlink():
            raise ValueError('백업 대상에 외부 연결이 있습니다.')
        if root.is_file():
            paths.append(root)
        elif root.is_dir():
            for p in root.rglob('*'):
                if p.is_symlink() or not p.resolve().is_relative_to(base):
                    raise ValueError('백업 대상에 외부 연결이 있습니다.')
                if p.is_file() and p.name not in ('.env', 'auth.json', 'accounts.bin') and not p.name.endswith(('.lock', '.tmp')):
                    paths.append(p)
    out = tempfile.TemporaryFile()
    try:
        manifest = {'export_version': EXPORT_VERSION, 'kind': kind, 'files': [],
                    'model_hash': read_json(base / 'teacher/teacher_model.json')['content_hash']}
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as z:
            for p in sorted(paths):
                relative = p.relative_to(base).as_posix()
                name = 'workspace/' + relative
                sha = hashlib.sha256(); size = 0
                with p.open('rb') as src, z.open(name, 'w', force_zip64=True) as dst:
                    for chunk in iter(lambda: src.read(1024 * 1024), b''):
                        sha.update(chunk); size += len(chunk); dst.write(chunk)
                manifest['files'].append({'path': name, 'bytes': size, 'sha256': sha.hexdigest()})
            if kind == 'recognition':
                # Also include the exact model-time extraction snapshot (including demo/JSON imports).
                m = read_json(base / 'teacher/teacher_model.json')
                body = json.dumps({'model_hash': m['content_hash'], 'sources': [
                    pick(s, ('id', 'title', 'sha256', 'excerpts', 'perception', 'extraction_status'))
                    for s in m.get('material_sources', [])]}, ensure_ascii=False).encode()
                z.writestr('model-recognition.json', body)
                manifest['files'].append({'path': 'model-recognition.json', 'bytes': len(body),
                                          'sha256': hashlib.sha256(body).hexdigest()})
            z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            z.writestr('README.txt', ('Backspace local ' + kind + ' export\n'
                'Contains private learning data. No API keys or ChatGPT login credentials.\n'
                'manifest.json lists SHA-256 of every data file.\n'
                + ('Complete workspace snapshot including originals, memories, histories and held-out exams.\n'
                   'Restore workspace/ into state/web/workspace/ of a compatible Backspace install while stopped.\n'
                   'Preserve the destination first; this archive does not include code or Python dependencies.\n'
                   if kind == 'backup' else 'Recognition records and model-time text snapshots only; not a complete restore archive.\n')))
        out.seek(0)
        return out
    except BaseException:
        out.close()
        raise
