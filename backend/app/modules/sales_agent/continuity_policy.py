"""Conversation control requires current evidence, never a model label alone."""
import hashlib
import re

from app.modules.governance.services import escalation_reason, request_attribution

STOP_WORDS = {'STOP', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT'}
HARD_VIOLATIONS = {'tenant_scope_mismatch', 'demo_external_contact_forbidden'}


def explicit_opt_out(text):
    if text.strip().upper() in STOP_WORDS:
        return True
    current = request_attribution(text)['current_text']
    for clause in re.split(r'[.!?;\n]|\b(?:but|pero|however)\b',current,flags=re.I):
        if re.search(
            r"^\s*(?:(?:please|por favor)[, ]+)?(?:"
            r"(?:do not|don't|don’t|stop)\s+(?:send(?:ing)?\s+me\s+(?:any\s+)?(?:more\s+)?messages|messag(?:e|ing)\s+me(?:\s+again)?|contact(?:ing)?\s+me)|"
            r"unsubscribe me|remove me from (?:your|the) (?:contact|mailing) list|"
            r"no me (?:env[ií]es|mandes)\s+(?:m[aá]s\s+)?mensajes|deja de (?:escribirme|contactarme)|no quiero recibir m[aá]s mensajes)\b(?:\s+(?:again|anymore|please|thanks|por favor))*\s*$",
            clause,re.I):
            return True
    return False


def evidenced_pause_reason(text):
    """Only an explicit handoff or a concrete security request pauses the chat.

    Legal/commercial exceptions need approval of the action, not a silent chat
    shutdown. Negated/reported requests are excluded before matching.
    """
    reason = escalation_reason(text)
    current = request_attribution(text)['current_text']
    own_advisor = re.search(r'\b(?:my advisor|mi asesor|mi asesora)\b',current,re.I) and not re.search(r'\b(?:transfer|connect|p[aá]same)\b',current,re.I)
    third_party = re.match(r'^\s*(?:my (?:friend|colleague|wife|husband)|mi (?:amigo|colega|esposa|esposo))\b',current,re.I)
    if reason == 'HUMAN_REQUESTED' and not own_advisor and not third_party and (
        re.search(r'\b(?:talk|speak|call|contact|transfer|hablar|llamar|comunicar|p[aá]same|atienda)\b',current,re.I) or
        re.fullmatch(r'\s*(?:I (?:want|need)|quiero|necesito) (?:a |an |un |una )?(?:human|person|advisor|sales representative|persona|asesor|asesora)[.! ]*',current,re.I)):
        return reason
    for clause in re.split(r'[.!?;\n]|\b(?:but|pero|however)\b', current, flags=re.I):
        if re.search(r"\b(?:don't|don’t|do not|not asking|no quiero|no necesito|no me)\b", clause, re.I):
            continue
        if re.search(r'\b(?:real colleague|human|persona|asesor)\b.{0,30}\b(?:take over|atienda|atiendas)\b', clause, re.I):
            return 'HUMAN_REQUESTED'
        if re.search(r'^\s*(?:(?:please|can you|could you|por favor|puedes)\s+)?(?:reveal|show|give|send|access|steal|bypass|mu[eé]strame|dame|revela|robar)\b', clause, re.I) and re.search(
            r"\b(?:private (?:account )?(?:passwords?|credentials|leads)|another company['’]s (?:private )?(?:leads|data)|"
            r"contrase[nñ]as? privadas?|credenciales privadas?|datos de otra empresa)\b", clause, re.I):
            return 'SECURITY'
    return None


def trigger_fingerprint(conversation_id, reason, evidence):
    normalized = ' '.join((evidence or '').casefold().split())
    return hashlib.sha256(f'{conversation_id}:{reason}:{normalized}'.encode()).hexdigest()


def dismissed_trigger(lead, conversation_id, reason, evidence):
    dismissed = (lead.meta_form_data or {}).get('dismissed_pause_triggers') or []
    return trigger_fingerprint(conversation_id, reason, evidence) in dismissed


def confirmed_controls(understanding, text, *, pause_reason=None):
    """An ungrounded human/opt-out classification asks instead of executing."""
    suspicious = any(r.polarity == 'request' and (
        r.topic.value == 'human' and not pause_reason or
        r.topic.value == 'opt_out' and not explicit_opt_out(text)) for r in understanding.requests)
    if not suspicious:
        return understanding
    return understanding.model_copy(update={
        'requires_clarification': True,
        'clarification_question': ('Would you like me to transfer this conversation to the Sales team?' if any(r.topic.value=='human' and r.polarity=='request' for r in understanding.requests)
                                   else 'Do you want to stop all messages from us, or continue with the property information? Reply STOP to unsubscribe.'),
    })
