"""P3-A: property identity gate for customer-facing content.

Only approved catalog names are inserted. This is not permission to invent
property facts, material coverage, an appointment or a resource URL.
"""
import re

VERSION = 'sales-property-reply-anchor/1.0'
BOUND_TOPICS = frozenset({'property_details', 'pricing', 'amenities', 'location',
                          'materials', 'appointment', 'delivery'})


def material_scope_ok(tasks, selected_property_id):
    """Mixed/unbound material tasks must never borrow the selected property."""
    if not selected_property_id or not tasks:
        return True
    return all(task.property_id == selected_property_id for task in tasks)


def anchor(text, selected_id, properties, *, topics=(), property_catalog=False,
           material_shared=False, booking_answer=False):
    """Return (rendered_text, audit) without altering verified fact wording."""
    if not text or not selected_id or property_catalog:
        return text, None
    if not (BOUND_TOPICS.intersection(topics) or material_shared or booking_answer):
        return text, None
    selected = [p for p in properties if p.get('id') == selected_id]
    if len(selected) != 1 or not selected[0].get('property_type'):
        # Never fabricate the name of a missing or foreign property.
        return text, None
    name = str(selected[0]['property_type']).strip()
    if not name or '\n' in name or len(name) > 180:
        return text, None
    # Already clearly identified at the start of this reply; do not repeat it.
    beginning = text[:220]
    if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', beginning, re.I):
        return text, {'version':VERSION, 'property_id':selected_id, 'action':'already_named'}
    return name + '\n\n' + text, {
        'version':VERSION, 'property_id':selected_id, 'action':'prepend_verified_property_name'}
