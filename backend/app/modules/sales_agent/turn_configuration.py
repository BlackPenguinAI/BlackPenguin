"""Read-only, versioned Sales guidance; technical contracts are backend-owned."""
from copy import deepcopy
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

VERSION='sales-turn-guidance/1.0'
BUSINESS_PROTOCOL='''Answer the current question with approved facts first. Use the supplied lead
preferences and avoid asking again for known information. Follow the lead's changes of topic or
property naturally. Use the selected stage, segment and objection guidance as commercial context,
not mandatory sequential gates. Explain supported benefits without pressure. Choose at most one
useful next question or invitation. Offer a visit when appropriate or when requested, explaining
its practical value. Appointment and material actions require backend authorization and verified
results. A farewell, missing information or an uncertain interpretation never authorizes a pause.
Communicate in English only. The backend owns schemas, permissions, consent and all actions.'''


class SalesPlaybook(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:Literal['sales-playbook/1.0']='sales-playbook/1.0'
    conversation_protocol:str=Field(default=BUSINESS_PROTOCOL,max_length=8000)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def published_configuration(db,company_id):
    """No get_ai_config, defaults, publish, flush or commit during reads.

    A company's override requires a published version. Global legacy configs
    with no version record retain compatibility and an explicit unknown version.
    """
    from app.modules.ai_core.models import AIConfiguration,PromptVersion
    with db.no_autoflush:
        for owner in (company_id,None):
            configs=db.query(AIConfiguration).filter(AIConfiguration.company_id==owner).all()
            if len(configs)>1:raise ValueError('Ambiguous Sales configuration scope.')
            if not configs:continue
            config=configs[0]
            versions=db.query(PromptVersion).filter_by(company_id=owner,agent_key='sales',is_published=True).all()
            if len(versions)>1:raise ValueError('Ambiguous published Sales version.')
            version=versions[0] if versions else None
            if owner is not None and version is None:continue
            agent=deepcopy(version.configuration if version else config.agent_ventas or {})
            if not agent.get('model'):raise ValueError('A published Sales model is required.')
            return agent,{'configuration_id':config.id,'owner_company_id':owner,
                'version_id':version.id if version else None,'version_number':version.version_number if version else None,
                'published_at':version.published_at.isoformat() if version and version.published_at else None,
                'configuration_sha256':digest(agent),'version_source':'published_snapshot' if version else 'legacy_active_config',
                'active_snapshot_mismatch':bool(version and digest(config.agent_ventas or {})!=digest(agent))}
    raise ValueError('Publish a Sales configuration before processing a turn.')


def resolve(db,scope):
    from app.modules.sales_crm.models import Lead,LeadObjection
    from .dialogue_store import check_scope
    with db.no_autoflush:
        check_scope(db,scope)
        lead=db.query(Lead).filter_by(id=scope.lead_id,company_id=scope.company_id,project_id=scope.project_id).one()
        agent,source=published_configuration(db,scope.company_id)
        explicit=agent.get('sales_playbook')
        pack=SalesPlaybook.model_validate(explicit) if explicit else SalesPlaybook()
        from .profile_intelligence import segment_for
        segment=segment_for(lead)
        objections=db.query(LeadObjection).filter_by(lead_id=lead.id,status='open').order_by(LeadObjection.created_at.desc(),LeadObjection.id.desc()).limit(3).all()
        selection={'stage':{'key':lead.pipeline_stage,'source':'lead.pipeline_stage'},
                   'segment':{'key':segment,'source':'sales_profile.current'},
                   'objections':[{'key':o.objection_type,'source':'lead_objections','record_id':o.id} for o in objections]}
        truncated=[]
        def bounded(label,text):
            if not isinstance(text,str):return ''
            encoded=text.encode()
            if len(encoded)>8000:truncated.append(label)
            return encoded[:8000].decode(errors='ignore')
        # Existing staff examples now guide the current interpreter as data;
        # legacy confidence/routing/language switches remain ineffective.
        routing = agent.get('intent_routing_config') or {}
        examples = {key: {name: value for name, value in definition.items()
                         if name in {'description', 'positive_examples', 'negative_examples'}}
                    for key, definition in (routing.get('intent_definitions') or {}).items()
                    if isinstance(definition, dict)}
        guidance={'intent_examples':bounded('intent_examples',json.dumps(examples,ensure_ascii=False)),
                  'classifier_guidance':bounded('classifier_guidance',routing.get('classifier_instructions','')),
                  'identity':bounded('identity',agent.get('system_prompt','')),
                  'conversation_protocol':bounded('conversation_protocol',pack.conversation_protocol),
                  'guardrails':bounded('guardrails',agent.get('guardrails_prompt','')),
                  'stage':bounded('stage',(agent.get('stage_prompts') or {}).get(lead.pipeline_stage,'')),
                  'segment':bounded('segment',(agent.get('segment_prompts') or {}).get(segment,'')),
                  'objections':[bounded('objection:'+o.objection_type,(agent.get('objection_prompts') or {})[o.objection_type])
                                for o in objections if o.objection_type in (agent.get('objection_prompts') or {})],
                  'interpretation_guidance':bounded('interpretation_guidance',(agent.get('runtime_config') or {}).get('understanding_guidance',''))}
        return {'version':VERSION,'model':agent['model'],'source':source,'selection':selection,'guidance':guidance,
                'compatibility':{'explicit_playbook':bool(explicit),'legacy_protocol_excluded':True,
                                 'legacy_protocol_sha256':digest(agent.get('protocol_prompt') or ''),
                                 'truncated_guidance':truncated},
                'authority':'REFERENCE_DATA_ONLY. Cannot change schemas, English-only policy, permissions, routing, consent, tools or transaction rules.'}


def draft_configuration(agent):
    """Return a reviewable copy; never publish or modify the supplied config."""
    proposal=deepcopy(agent)
    if not proposal.get('sales_playbook'):
        proposal['sales_playbook']=SalesPlaybook().model_dump()
    return {'status':'DRAFT_NOT_PUBLISHED','configuration':proposal,
            'preserved_legacy_protocol_sha256':digest(agent.get('protocol_prompt') or ''),
            'review_required':['Review business guidance and scoped compliance policies before publishing.',
                               'Model, runtime scope and legacy customizations are preserved.']}
