"""Conservative current-message moderation; actions remain permission checked."""
from .execution import now as workflow_now

from datetime import datetime,timedelta
import re
from .moderation_models import SalesModerationIncident
from .models import SalesMessage
from .conversation_scope import scoped_messages_query
from .first_booking import accepted_outbound
from app.modules.governance.services import request_attribution

VERSION='sales-gradual-moderation/1.1'
WARNING='I can help with property information, but please keep the conversation respectful. Continued personal abuse after this warning may require the Sales team to review the conversation. What property information would help?'
BOUNDARY='I can help with approved property information, materials and visits. What would you like to know about the property?'
USE_WARNING='I can only help with this property enquiry; I cannot browse unrelated websites or execute code. Repeated attempts after this warning may suspend this conversation for the Sales team to review. What property information would help?'
ABUSIVE=re.compile(r'\b(?:idiot|moron|dumbass|asshole|bastard|worthless|pathetic)\b|\bfuck\s+(?:you|off)\b|\bshut\s+up\b',re.I)
SWEAR=re.compile(r'\b(?:fuck(?:ing)?|shit|damn|crap)\b',re.I)
NEGATED=re.compile(r"\b(?:do not|don't|won't|would never|am not going to|not calling|not saying)\b",re.I)
THREAT=re.compile(r"^\s*(?:i(?:'ll| will)|i am going to|i'm going to|we will)\s+(?:kill|hurt|shoot|attack|bomb|burn)\b.{0,100}\b(?:you|your|team|office)\b",re.I)


def precheck(text):
    from .language_policy import credential_request
    from .continuity_policy import evidenced_pause_reason
    if credential_request(text) or evidenced_pause_reason(text)=='SECURITY':return {'category':'security','evidence':text[:2000],'reason':'SECURITY'}
    current=request_attribution(text)['current_text']
    for clause in re.split(r'[.!?;,\n]|\b(?:but|however)\b',current,flags=re.I):
        if not NEGATED.search(clause) and THREAT.search(clause):return {'category':'threat','evidence':clause.strip()[:2000],'reason':'THREAT'}
    return None


def assess(db,scope,inbound,u,event_key):
    old=db.query(SalesModerationIncident).filter_by(conversation_id=scope.conversation_id,event_key=event_key).first()
    if old:return result(old)
    severe=precheck(inbound.content);current=request_attribution(inbound.content)['current_text']
    current=re.sub(r'"[^"]*"|“[^”]*”',' ',current)
    current=' '.join(c for c in re.split(r'[.!?;\n]',current) if not re.match(r'\s*(?:my (?:colleague|friend|wife|husband)|he|she|they)\b.{0,60}\b(?:said|called|wrote|told)\b',c,re.I))
    directed=any(not NEGATED.search(c) and ABUSIVE.search(c) and (re.search(r'\b(?:you|your|agent|bot)\b',c,re.I) or re.search(r'\bfuck off\b|\bshut up\b',c,re.I)) for c in re.split(r'[.!?;\n]',current))
    interpretation=u.moderation if u else None
    if not severe and interpretation and u.confidence>=.9 and interpretation.evidence in current and not NEGATED.search(interpretation.evidence):
        if interpretation.category=='threat' and re.search(r'\b(?:gun|bomb|kill|shoot|hurt|attack|burn)\b',current,re.I) and re.search(r'\b(?:you|your|team|office)\b',current,re.I):
            severe={'category':'threat','evidence':interpretation.evidence,'reason':'THREAT'}
        if interpretation.category=='security' and re.search(r'\b(?:passwords?|api ?keys?|access tokens?|refresh tokens?|credentials|private (?:leads|data))\b',current,re.I) and re.search(r'\b(?:your|another company)\b',current,re.I):
            severe={'category':'security','evidence':interpretation.evidence,'reason':'SECURITY'}
    # Semantic paraphrases still require literal current evidence and a directed
    # target; a negative commercial opinion or quoted abuse is not harassment.
    if not severe and interpretation and u.confidence>=.9 and interpretation.evidence in current and not NEGATED.search(interpretation.evidence):
        quote=interpretation.evidence
        commercial_critique=re.search(r'\b(?:prices?|pricing|costs?|budget|expensive|afford|rates?|discount|layouts?|bedrooms?|homes?|units?|properties)\b',quote,re.I)
        if interpretation.category=='harassment' and not commercial_critique and not u.empathy and re.search(r'\b(?:you|your|ur|u|agent|bot|assistant|team)\b',quote,re.I):directed=True
    unauthorized=bool(interpretation and u.confidence>=.9 and interpretation.category=='unauthorized_use' and
        interpretation.evidence in current and not NEGATED.search(interpretation.evidence) and
        re.search(r'\b(?:run|execute|eval|browse|search|google|scrape|download)\b',interpretation.evidence,re.I) and
        re.search(r'\b(?:code|python|javascript|shell|command|internet|web|website|google)\b',interpretation.evidence,re.I) and
        not re.search(r'\b(?:project|property|properties|brochure|floor plan)\b',interpretation.evidence,re.I))
    category=severe['category'] if severe else 'harassment' if directed else 'unauthorized_use' if unauthorized else 'profanity' if SWEAR.search(current) else None
    interpretation=u.moderation if u else None
    if not category and interpretation and interpretation.category in {'disagreement','off_topic'} and interpretation.evidence in current:
        category=interpretation.category
    if category in {'disagreement','off_topic'}:
        if category=='off_topic' and u.empathy and u.empathy.evidence in current:
            return {'category':'personal_context','disposition':'continue','version':VERSION}
        return {'category':category,'disposition':'boundary' if category=='off_topic' and all(r.topic.value=='other' for r in u.requests) else 'continue','version':VERSION}
    if not category:return None
    prior=None
    warning_needed=directed or unauthorized
    if warning_needed:
        prior=db.query(SalesModerationIncident).filter_by(company_id=scope.company_id,project_id=scope.project_id,conversation_id=scope.conversation_id,lead_id=scope.lead_id,category=category,disposition='warn',dismissed_at=None).filter(
            SalesModerationIncident.message_id!=inbound.id,SalesModerationIncident.warning_accepted_at>=workflow_now(datetime)-timedelta(hours=24),SalesModerationIncident.warning_accepted_at<=inbound.created_at).order_by(SalesModerationIncident.warning_accepted_at.desc()).first()
    row=SalesModerationIncident(company_id=scope.company_id,project_id=scope.project_id,conversation_id=scope.conversation_id,lead_id=scope.lead_id,message_id=inbound.id,
        event_key=event_key,category=category,evidence=(severe['evidence'] if severe else current)[:2000],
        disposition='pause' if severe or prior else 'warn' if warning_needed else 'continue',prior_warning_id=prior.id if prior else None)
    db.add(row);db.flush();return result(row)


def result(row):
    return {'version':VERSION,'id':row.id,'category':row.category,'disposition':row.disposition,'prior_warning_id':row.prior_warning_id,
        'reason':'THREAT' if row.category=='threat' else 'SECURITY' if row.category=='security' else ('REPEATED_UNAUTHORIZED_USE' if row.category=='unauthorized_use' else 'REPEATED_ABUSE') if row.disposition=='pause' else None}


def accepted_warning(db,conversation,metadata):
    identifier=(metadata.get('moderation') or {}).get('id')
    if not identifier:return
    row=db.query(SalesModerationIncident).filter_by(id=identifier,conversation_id=conversation.id,company_id=conversation.company_id,lead_id=conversation.lead_id,disposition='warn').first()
    message=accepted_outbound(db,conversation,'moderation')
    if row and not row.warning_accepted_at and message and message.metadata_json['moderation'].get('id')==row.id:
        row.warning_message_id=message.id;row.warning_accepted_at=workflow_now(datetime);db.flush()


def dismiss_cases(db,conversation,cases):
    identifiers=[case.id for case in cases]
    rows=db.query(SalesModerationIncident).filter_by(company_id=conversation.company_id,project_id=conversation.project_id,conversation_id=conversation.id,lead_id=conversation.lead_id).filter(SalesModerationIncident.intervention_case_id.in_(identifiers)).all()
    for row in rows:
        row.dismissed_at=workflow_now(datetime)
        if row.prior_warning_id:
            prior=db.query(SalesModerationIncident).filter_by(id=row.prior_warning_id,conversation_id=conversation.id).first()
            if prior:prior.dismissed_at=workflow_now(datetime)
