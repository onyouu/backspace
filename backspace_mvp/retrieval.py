"""Bounded lexical retrieval over original material text, independent of inferred edges."""
import math
import re
from collections import Counter
from .pipeline import digest


def terms(text):
    words = re.findall(r'[가-힣A-Za-z0-9]+', text.casefold())
    result = set(words)
    # Korean particles make exact whitespace token matching brittle.
    for word in words:
        if re.search('[가-힣]', word):
            result.update(word[i:i + 3] for i in range(len(word) - 2))
    return result


def material_blocks(data, limit=1400):
    blocks = []
    for source in data['sources']:
        if source['kind'] != 'learning_material':
            continue
        for excerpt in source['excerpts']:
            text = excerpt['text']
            # Preserve full original substrings and offsets; never claim page completeness.
            units = list(re.finditer(r'[^\n。.!?]+(?:[。.!?]|\n|$)', text))
            start = end = None
            for unit in units:
                if start is not None and unit.end() - start > limit:
                    blocks.append(block(source, excerpt, start, end))
                    start = None
                if start is None:
                    start = unit.start()
                end = unit.end()
            if start is not None:
                blocks.append(block(source, excerpt, start, end))
    return blocks


def block(source, excerpt, start, end):
    return {'block_id': 'b_' + digest([source['sha256'], source['id'], excerpt['locator'], start, end])[:20],
            'source_id': source['id'], 'locator': excerpt['locator'], 'title': source['title'],
            'source_sha256': source['sha256'], 'start': start, 'end': end,
            'text': excerpt['text'][start:end]}


def retrieve(data, query, top_k=6, max_chars=10000):
    blocks = material_blocks(data)
    query_terms = terms(query)
    frequencies = Counter(t for b in blocks for t in terms(b['text']))
    seeds = [name for c in data['concepts'] for name in [c['label'], *c['aliases']]
             if name.casefold() in query.casefold()]
    scored = []
    for b in blocks:
        overlap = terms(b['text']) & query_terms
        score = sum(math.log(1 + len(blocks) / frequencies[t]) for t in overlap)
        score += 2 * sum(name.casefold() in b['text'].casefold() for name in seeds)
        if score > 0:
            scored.append((score, b))
    scored.sort(key=lambda row: (-row[0], row[1]['block_id']))
    selected, size = [], 0
    for score, b in scored:
        if len(selected) >= top_k:
            break
        if size + len(b['text']) > max_chars:
            continue
        selected.append({**b, 'score': round(score, 4)})
        size += len(b['text'])
    return {'method': 'lexical_original_blocks_v1', 'query': query, 'total_blocks': len(blocks),
            'matched_blocks': len(scored), 'selected_blocks': selected,
            'context_chars': size, 'budget_limited': len(selected) < len(scored),
            'max_chars': max_chars, 'top_k': top_k,
            'corpus_hash': digest([(b['block_id'], b['source_sha256']) for b in blocks])}
