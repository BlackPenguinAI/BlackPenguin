"""Evidence of a focused catalog fact provided to the SDK, not proof of its thoughts.

Only synthetic HEI-06 tests import this module. Do not retain prompts, context,
IDs, contact data or model output in the diagnostic export.
"""
from __future__ import annotations
import re


class FocusGrounding:
    """Observe the actual TurnRequest immediately before invoking the SDK.

    A successful tool call is optional for an already supplied fact, but an
    exact current scoped snapshot is mandatory. No fake tool observations.
    """
    def __init__(self):
        self.expected = None
        self.count = 0
        self.verified = False

    def expect(self, *, scope, message, ref, name, field, value, ordinal=False):
        assert self.expected is None
        assert field in {'bedrooms','bathrooms'} and type(value) is int
        self.expected = (scope, message, ref, name, field, value, ordinal)
        self.count = 0
        self.verified = False

    def observe(self, request):
        if self.expected is None:
            return
        self.count += 1
        scope, message, ref, name, field, value, ordinal = self.expected
        c = request.verified_context
        focus = c.get('conversation_focus') or {}
        prop = c.get('focused_property') or {}
        rows = [r for r in (c.get('available_property_types') or []) if r.get('id') == ref]
        choice = c.get('resolved_visible_choice') or {}
        self.verified = bool(
            request.scope == scope and request.message == message and request.channel == 'sms'
            and (c.get('company') or {}).get('id') == scope.company_id
            and (c.get('project') or {}).get('id') == scope.project_id
            and (c.get('registered_contact') or {}).get('id') == scope.lead_id
            and focus.get('project_id') == scope.project_id and focus.get('ambiguous') is False
            and focus.get('property_type_id') == ref and focus.get('unit_id') is None
            and prop.get('kind') == 'property_type' and prop.get('id') == ref
            and prop.get('reference') == ref and prop.get('display_name') == name
            and len(rows) == 1 and rows[0].get('property_type') == name
            and type(prop.get(field)) in (int,float) and prop[field] == value
            and type(rows[0].get(field)) in (int,float) and rows[0][field] == value
            and (not ordinal or (choice.get('type') == 'property' and choice.get('status') == 'resolved'
                 and (choice.get('choice') or {}).get('unit_id') == ref))
        )

    def finish(self, *, observations, trace=None):
        assert self.expected is not None
        field = self.expected[4]
        details = [o for o in observations if o.get('tool') == 'get_unit_details']
        called = any(o.get('status') == 'executed' and o.get('error_code') is None for o in details)
        rejected = any(o.get('status') != 'executed' or o.get('error_code') is not None for o in details)
        valid = self.count == 1 and self.verified and not rejected
        if trace is not None:
            trace.add('fact_grounding', field=field, verified_context=bool(self.count == 1 and self.verified),
                      details_tool_executed=called, details_tool_rejected=rejected)
        self.expected = None
        assert valid, 'Missing, ambiguous, conflicting or non-current focused catalog evidence'
        return 'verified_context_and_tool' if called else 'verified_context'


def assert_fact_reply(text, *, name, field, value):
    """Check the accepted response, not just the model draft, for this fixture."""
    assert field in {'bedrooms','bathrooms'} and type(value) is int
    plain = re.sub(r'[*_`]', '', text)
    assert name.casefold() in plain.casefold()
    # Do not accept a different property or a conflicting number of the queried
    # rooms. The fixture uses distinct bathroom counts to disambiguate choices.
    other = 'Oakwood' if name == 'Van Buren' else 'Van Buren'
    assert other.casefold() not in plain.casefold()
    words = dict(zip(('zero','one','two','three','four','five','six','seven','eight','nine','ten'), range(11)))
    pattern = r'\b(\d+(?:\.\d+)?|'+'|'.join(words)+r')\s*[- ]\s*'+field.rstrip('s')+r's?\b'
    values = [words[x.casefold()] if x.casefold() in words else float(x)
              for x in re.findall(pattern, plain, re.I)]
    assert values and all(v == value for v in values), 'Missing or conflicting room count in accepted reply'
