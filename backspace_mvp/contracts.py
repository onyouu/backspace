"""Small analysis/review contracts. Reviews are model judgements, never human approval."""
def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


TEXT = {'type': 'string', 'minLength': 1}
TEXTS = {'type': 'array', 'items': TEXT}
STRINGS = {**TEXTS, 'minItems': 1}
INDEX = {'type': 'integer', 'minimum': 0}
INDICES = {'type': 'array', 'items': INDEX, 'uniqueItems': True}
REFS = {'type': 'array', 'items': obj({'block_id': TEXT, 'quote': TEXT})}
MATERIAL_TYPES = ['causes', 'part_of', 'contrasts', 'requires', 'exception_to', 'related_to', 'explains', 'produces', 'role_in']
CONFIDENCE = {'type': 'number', 'minimum': 0, 'maximum': 1}


def question_contract(codes):
    return obj({
        'task': obj({'description': TEXT, 'quote': TEXT, 'confidence': CONFIDENCE}),
        'confidence': CONFIDENCE,
        'concepts': {'type': 'array', 'minItems': 1, 'items': obj({'label': TEXT, 'step': INDEX, 'confidence': CONFIDENCE})},
        'steps': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': obj({
            'code': {'enum': codes}, 'label': TEXT, 'input': TEXT, 'output': TEXT,
            'success_criteria': STRINGS, 'conditions': TEXTS, 'practice': TEXT,
            'claim_indices': INDICES, 'criterion_references': REFS, 'confidence': CONFIDENCE})},
        'links': {'type': 'array', 'items': obj({'from': INDEX, 'to': INDEX,
            'relation': {'enum': ['precedes', 'supports', 'requires', 'contrasts']},
            'explanation': TEXT})},
        'claims': {'type': 'array', 'minItems': 1, 'maxItems': 6, 'items': obj({
            'statement': TEXT, 'conditions': TEXTS, 'references': REFS, 'confidence': CONFIDENCE})},
        'answer_requirements': STRINGS,
        'intent': obj({'objective': TEXT, 'success_criteria': STRINGS, 'confidence': CONFIDENCE})})


VERDICT = obj({'index': INDEX,
    'status': {'enum': ['supported', 'contradicted', 'insufficient_evidence', 'domain_knowledge_needs_review']},
    'reason': TEXT})
VERDICTS = {'type': 'array', 'items': VERDICT}
QUESTION_REVIEW = obj({'task_verdicts': VERDICTS, 'claim_verdicts': VERDICTS, 'step_verdicts': VERDICTS,
    'link_verdicts': VERDICTS, 'missing_requirements': TEXTS, 'issues': TEXTS})
MATERIAL = obj({'concepts': {'type': 'array', 'maxItems': 40, 'items': obj({
    'label': TEXT, 'surface_form': TEXT, 'quote': TEXT, 'confidence': CONFIDENCE,
    'explicit_emphasis': TEXTS})}, 'relations': {'type': 'array', 'maxItems': 40, 'items': obj({
    'from_label': TEXT, 'to_label': TEXT, 'relation': {'enum': MATERIAL_TYPES},
    'statement': TEXT, 'conditions': TEXTS, 'quote': TEXT, 'confidence': CONFIDENCE})}})
MATERIAL_REVIEW = obj({'verdicts': VERDICTS})
