"""Explicit source-span mapping. Never guess which key belongs to which question."""
from pathlib import Path
from jsonschema import Draft202012Validator


def load_answer_keys(manifest_path, exam_id):
    from .model import read_json
    from .pipeline import read_source, digest
    path = Path(manifest_path).resolve()
    manifest = read_json(path)
    schema = read_json(Path(__file__).parent / 'schemas/answer_key_manifest.schema.json')
    Draft202012Validator(schema).validate(manifest)
    if manifest['exam_id'] != exam_id:
        raise ValueError('정답·해설 매핑의 exam_id가 시험과 다릅니다.')
    sources, mapping = {}, {}
    for entry in manifest['entries']:
        source = read_source(path.parent / entry['source'], 'answer_key', exam_id)
        sources[source['id']] = source
        text = next((p['text'] for p in source['excerpts'] if p['locator'] == entry['locator']), None)
        if text is None or entry['quote'] not in text:
            raise ValueError('정답·해설 인용의 원문 위치가 일치하지 않습니다.')
        start = text.index(entry['quote'])
        block = {'source_id': source['id'], 'source_sha256': source['sha256'], 'locator': entry['locator'],
                 'start': start, 'end': start + len(entry['quote']), 'text': entry['quote']}
        block['block_id'] = 'ak_' + digest([source['sha256'], source['id'], entry['locator'], start, block['end']])[:20]
        key = (entry['exam_locator'], entry['question_number'])
        values = mapping.setdefault(key, [])
        if any(b['block_id'] == block['block_id'] for b in values):
            raise ValueError('동일한 정답·해설 매핑이 중복되었습니다.')
        values.append(block)
        if sum(len(b['text']) for b in values) > 6000:
            raise ValueError('한 문항의 정답·해설이 6000자를 넘습니다. 필요한 원문 범위를 명시해 줄이세요.')
    identity = digest([manifest, sorted((s['id'], s['sha256']) for s in sources.values())])
    return list(sources.values()), mapping, identity


def saved_answer_keys(data, exam_source_id):
    """An explicit refresh without a new manifest retains its previous source snapshot."""
    mapping = {}
    ids = set()
    for question in data['questions']:
        if any(e['source_id'] == exam_source_id for e in question['evidence']):
            context = question.get('answer_key_context')
            if context and context['status'] == 'provided':
                mapping[(context['exam_locator'], question['title'])] = context['blocks']
                ids.update(b['source_id'] for b in context['blocks'])
    return [s for s in data['sources'] if s['id'] in ids], mapping
