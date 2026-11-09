"""Anchor model quotations to this message without fuzzy/semantic substitution."""
import re


class EvidenceError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('Evidence must be an exact non-empty substring of the current message.')


def quotations(payload):
    for key in ('requests', 'constraints', 'alternatives', 'references', 'preferences', 'releases', 'personal_facts', 'preference_withdrawals', 'objections'):
        for index, item in enumerate(payload.get(key) or []):
            yield item, 'evidence', [key, index, 'evidence']
    for key in ('visit', 'reschedule', 'cancellation', 'wait', 'moderation', 'courtesy', 'comparison', 'empathy'):
        item = payload.get(key)
        if not item:
            continue
        for field, value in item.items():
            if field == 'evidence' or key in {'reschedule', 'cancellation', 'wait'} and field not in {'action', 'timing'}:
                if isinstance(value, str):
                    yield item, field, [key, field]
        for field, value in (item.get('timing') or {}).items():
            if field != 'time_relation' and value is not None:
                yield item['timing'], field, [key, 'timing', field]


def normalized(value):
    chars, positions = [], []
    for index, char in enumerate(value):
        char = {'’': "'", '‘': "'", '“': '"', '”': '"'}.get(char, char)
        if char.isspace():
            if chars and chars[-1] == ' ':
                continue
            char = ' '
        for folded in char.casefold():
            chars.append(folded)
            positions.append(index)
    return ''.join(chars), positions


def anchor(payload, inbound, *, repair_format=False):
    """A unique reversible format match may recover the original exact quotation.

    Never drop punctuation/words, correct spelling, search history, or substitute
    the whole message. Evidence problems contain field paths, not private text.
    """
    issues = []
    original, positions = normalized(inbound)
    for item, key, path in quotations(payload):
        quote = item[key]
        if quote.strip() and quote in inbound:
            continue
        recovered = None
        if repair_format and quote.strip():
            needle = normalized(quote)[0].strip()
            matches = list(re.finditer(re.escape(needle), original)) if needle else []
            if len(matches) == 1:
                match = matches[0]
                recovered = inbound[positions[match.start()]:positions[match.end()-1]+1]
                if normalized(recovered)[0] != needle:
                    recovered = None
        if recovered is not None:
            item[key] = recovered
        else:
            issues.append({'location': path, 'type': 'evidence_mismatch',
                           'message': 'Copy an exact non-empty quote from current_message for this field. Do not paraphrase, correct spelling, or quote history.'})
    if issues:
        raise EvidenceError(issues[:20])
    return payload
