"""Application-owned, versioned source slices. Models choose IDs, never quotations."""
from pathlib import Path
from jsonschema import Draft202012Validator
from .model import read_json
from .pipeline import digest, save

VERSION = 'source-span-1'


def source_version(source):
    p = source.get('perception', {})
    return digest([VERSION, source['id'], source['sha256'], p.get('version'), p.get('content_hash'), source['excerpts']])


def spans_for(source, locator, start=0, end=None, *, max_chars=320):
    from .perception import transcription_refs
    text = next(p['text'] for p in source['excerpts'] if p['locator'] == locator)
    end = len(text) if end is None else end
    if not 0 <= start <= end <= len(text): raise ValueError('Source span boundary outside current source')
    version = source_version(source); rows = []
    while start < end:
        stop = min(end, start+max_chars)
        if stop < end:
            boundary = text.rfind('\n', start+max_chars//2, stop)
            if boundary >= 0: stop = boundary+1
        value = text[start:stop]
        if value.strip():
            provenance = transcription_refs(source, locator, start, stop)
            row = {'span_id': 'sp_'+digest([source['id'], version, locator, start, stop])[:28],
                'source_id': source['id'], 'source_sha256': source['sha256'], 'source_version': version,
                'locator': locator, 'page': locator, 'region_id': [b['id'] for b in provenance],
                'start_offset': start, 'end_offset': stop, 'text': value, 'source_type': source['kind'],
                'ocr_provenance': provenance, 'perception_version': source.get('perception',{}).get('version','native'),
                'status': 'current'}
            Draft202012Validator(read_json(Path(__file__).parent/'schemas/source_span.schema.json')).validate(row)
            rows.append(row)
        start = stop
    return rows


def resolve(ids, spans, source):
    index = {s['span_id']:s for s in spans}; result = []
    if not ids: raise ValueError('missing_source_span_ids')
    for sid in ids:
        row = index.get(sid)
        if not row or row['source_id'] != source['id'] or row['source_version'] != source_version(source):
            raise ValueError('unknown_or_stale_source_span: '+sid)
        text = next(p['text'] for p in source['excerpts'] if p['locator']==row['locator'])
        if text[row['start_offset']:row['end_offset']] != row['text']: raise ValueError('source_span_integrity_failure')
        result.append(row)
    return result


def reference(span):
    return {'source_id':span['source_id'], 'locator':span['locator'], 'quote':span['text'],
        'span_id':span['span_id'], 'source_version':span['source_version'],
        'start_offset':span['start_offset'], 'end_offset':span['end_offset']}


def persist_spans(folder, source, spans):
    folder = Path(folder); path = folder/(source['id']+'.json')
    current = read_json(path) if path.exists() else None
    version = source_version(source)
    if current and current['source_version'] != version:
        save(folder/'history'/(source['id']+'-'+current['source_version']+'.json'), {**current,'status':'superseded'})
    existing = current['spans'] if current and current['source_version']==version else []
    rows = {s['span_id']:s for s in [*existing,*spans]}
    save(path, {'version':VERSION,'source_id':source['id'],'source_version':version,'status':'current','spans':list(rows.values())})
