"""Explicit staff-reviewed action restrictions, never a free-text policy compiler."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .turn_configuration import digest

TOPICS={'catalog','property_details','inventory','pricing','financing','delivery','amenities','location','materials','appointment'}


def standard_notes(notes):
    """Exact platform onboarding choices, not a free-text permission compiler."""
    choices = {'not applicable', 'use standard company compliance', 'no project-specific notes',
               'use standard company compliance; no project-specific notes'}
    values = notes if isinstance(notes, list) else [notes]
    return bool(values) and all(isinstance(value, str) and value.strip().casefold() in choices
                                for value in values)


class ActionRule(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=80)
    topics:list[Literal['catalog','property_details','inventory','pricing','financing','delivery','amenities','location','materials','appointment']]=Field(min_length=1,max_length=10)
    effect:Literal['require_review','deny']
    reason:str=Field(min_length=1,max_length=500)


class ActionPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:Literal['sales-action-policy/1.0']
    source_note_sha256:str|None=Field(default=None,pattern=r'^[0-9a-f]{64}$')
    rules:list[ActionRule]=Field(default_factory=list,max_length=30)


def resolve(db,scope,company,project,*,target_project_id=None):
    from app.modules.governance.models import KnowledgeGuidanceItem
    from app.modules.users.models import User,UserRole
    holds,unresolved,evidence=set(),[],[]
    with db.no_autoflush:
        from .dialogue_store import check_scope
        check_scope(db,scope)
        project_id=target_project_id or scope.project_id
        if target_project_id:
            from app.modules.projects.models import Project
            if not db.query(Project).filter_by(id=project_id,company_id=scope.company_id).first():
                raise PermissionError('Target policy is outside this Company.')
        records=db.query(KnowledgeGuidanceItem).filter(
            KnowledgeGuidanceItem.company_id==scope.company_id,
            KnowledgeGuidanceItem.kind=='sales_action_policy',KnowledgeGuidanceItem.status=='approved',
            KnowledgeGuidanceItem.approved_at.isnot(None),
            ((KnowledgeGuidanceItem.project_id==project_id)|(KnowledgeGuidanceItem.project_id.is_(None)))).all()
        for source,owner,notes in [('company',None,company.get('corporate_compliance_information')),
                                  ('project',project_id,project.get('compliance_notes'))]:
            matched=False
            note_hash=digest(notes) if notes not in (None,'',[],{}) and not standard_notes(notes) else None
            invalid=[]
            for record in (r for r in records if r.project_id==owner):
                actor=db.get(User,record.approved_by_user_id) if record.approved_by_user_id else None
                if not actor or actor.company_id!=scope.company_id or actor.role not in {UserRole.ADMIN,UserRole.ASSISTANT} or not actor.is_active or actor.deleted_at:
                    invalid.append(record.id);continue
                try:policy=ActionPolicy.model_validate_json(record.content)
                except ValueError:
                    invalid.append(record.id);continue
                matched |= policy.source_note_sha256==note_hash
                for rule in policy.rules:
                    holds.update(rule.topics)
                evidence.append({'scope':source,'record_id':record.id,'version':record.version,
                                 'approved_by_user_id':record.approved_by_user_id,
                                 'source_note_sha256':policy.source_note_sha256,'rules':[r.model_dump() for r in policy.rules]})
            if invalid or note_hash and not matched:
                # An unknown restriction cannot be waived by a keyword match,
                # Project override, or model. Keep assistance open, hold claims
                # whose permission has not been clarified, and expose the gap.
                holds.update(TOPICS)
                unresolved.append({'scope':source,'source_note_sha256':note_hash,
                                   'reason':'invalid_review_record' if invalid else 'explicit_policy_review_required',
                                   'invalid_record_ids':invalid})
    if holds & {'pricing','inventory'}:holds.update({'catalog','property_details','inventory','pricing'})
    return {'version':'sales-action-policy-resolution/1.0','held_topics':sorted(holds),
            'unresolved':unresolved,'evidence':evidence,'conversation_paused':False,
            'permission_grants':[]}
