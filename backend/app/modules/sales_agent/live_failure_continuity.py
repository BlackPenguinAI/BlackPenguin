"""Bounded response to a direct question about the immediately previous failure.

A processing fallback is not a request for human contact. No internal exception,
SQL, third-party detail, refund, scheduling or remedial action is exposed.
"""
import re

FALLBACKS = frozenset({
    'I couldn’t complete your request just now. Please try again in a moment.',
    'I’m still unable to complete that request. Please try again shortly.',
})


def explanation(current, previous):
    if not previous or previous not in FALLBACKS:
        return None
    if not re.fullmatch(r'\s*[¿]?\s*(?:what happened|what went wrong|qué pasó|que paso)\s*[?¿!]*\s*',
                        current or '',re.I):
        return None
    return ('I could not complete my previous response. Please repeat your property question '
            'or ask me to check current visit options. I can continue helping here.')
