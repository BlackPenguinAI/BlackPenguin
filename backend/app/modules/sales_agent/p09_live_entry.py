"""Real-only Meta lead activation at the P09 country routing boundary.

Unlike the legacy live driver, this entrypoint never calls
``prepare_meta_simulation`` for a real captured lead. When a country/provider
route is unavailable it leaves the lead blocked and creates no fake chat.
"""
from __future__ import annotations

from datetime import datetime

from app.db.postgres import SessionLocal
from app.integrations.messaging_gateway import (
    company_live_channel, destination_channel, live_provider,
)
from app.modules.governance.services import (
    enqueue_notification, next_allowed_proactive_time,
)
from app.modules.projects.models import Project, ProjectCampaign
from app.modules.sales_crm.models import FunnelStage, Lead
from app.modules.sales_agent.models import SalesMessage, SalesFollowUpJob
from app.modules.sales_agent.conversation_scope import scoped_messages_query
from app.modules.sales_agent.execution import now as workflow_now


def _block(db, lead: Lead) -> None:
    lead.agent_status = 'routing_blocked'
    lead.next_action_at = None
    enqueue_notification(
        db, company_id=lead.company_id, project_id=lead.project_id,
        event_type='lead_channel_blocked', entity_type='lead', entity_id=lead.id,
        payload={'title': 'Real messaging unavailable',
                 'body': 'The required country-based SMS/WhatsApp route is not ready. No message was sent.',
                 'action_url': f'/app/leads?lead={lead.id}',
                 'recipient_roles': ['admin', 'assistant']},
        dedupe_key=f'p09-channel-blocked:{lead.id}',
    )
    db.commit()


async def start_live_lead(lead_id: str) -> None:
    # The Meta webhook has already persisted the opportunity in its Company.
    # This worker uses a fresh session exactly as the existing live driver does.
    from app.modules.sales_agent import live_service as live

    db = SessionLocal()
    try:
        lead = db.query(Lead).filter(
            Lead.id == lead_id, Lead.is_demo.is_(False),
            Lead.deleted_at.is_(None),
        ).with_for_update().first()
        if not lead or not lead.project_id or lead.is_opt_out:
            return
        expected = destination_channel(lead.phone)
        channel = company_live_channel(
            db, company_id=lead.company_id, destination_phone=lead.phone,
        )
        if not channel or channel != expected:
            _block(db, lead)
            return
        provider = 'telnyx' if channel == 'whatsapp' else live_provider(
            db, company_id=lead.company_id,
        )
        if not provider:
            _block(db, lead)
            return
        lead.preferred_channel = channel
        project = db.query(Project).filter(
            Project.id == lead.project_id, Project.company_id == lead.company_id,
        ).one()
        campaign = (db.query(ProjectCampaign).filter(
            ProjectCampaign.id == lead.campaign_id,
            ProjectCampaign.project_id == project.id,
        ).first() if lead.campaign_id else None)
        live.ensure_contact(db, lead)
        conversation, should_send = live.get_or_create_live_conversation(
            db, lead, provider=provider,
        )
        prior_message_count = scoped_messages_query(
            db, conversation, lead_id=lead.id,
        ).filter(SalesMessage.status != 'failed').count()
        if not should_send and prior_message_count:
            db.commit()
            return
        allowed_at = next_allowed_proactive_time(
            db, company_id=lead.company_id, project_id=lead.project_id,
            now=workflow_now(datetime),
        )
        if allowed_at > workflow_now(datetime):
            if not db.query(SalesFollowUpJob).filter(
                SalesFollowUpJob.conversation_id == conversation.id,
                SalesFollowUpJob.status == 'pending',
            ).first():
                db.add(SalesFollowUpJob(
                    conversation_id=conversation.id,
                    idempotency_key=f'operating-window-initial:{lead.id}',
                    scheduled_at=allowed_at, status='pending',
                    reason='operating_window_initial', attempt_number=1,
                ))
            lead.next_action_at = allowed_at
            lead.agent_status = 'scheduled'
            db.commit()
            return
        content = live._initial_message(lead, project, campaign)
        event_kind = ('meta_lead_first_contact' if lead.platform.startswith('meta')
                      else 'manual_lead_first_contact')
        if prior_message_count:
            first_name = (lead.full_name or 'there').split()[0]
            content = (
                f'Hi {first_name}, I also received your interest in '
                f'{campaign.name if campaign else project.name}. '
                f"I'll continue here so your conversation stays in one place. "
                f'What would you like to know about {project.name}?'
            )
            event_kind = 'meta_lead_project_context_changed'
        # Same real provider dispatch as the production driver, without any
        # branch that materializes a fake simulation conversation or receipt.
        await live._dispatch(
            db, conversation=conversation, lead=lead, content=content,
            role='assistant', agent_run_id=None,
            metadata={'event_kind': event_kind, 'lead_id': lead.id,
                      'project_id': project.id},
            idempotency_key=f'live-initial:{lead.id}',
        )
        lead.agent_status = 'active'
        lead.funnel_stage = FunnelStage.CONTACTED
        lead.pipeline_stage = 'S01_RESEARCH'
        lead.last_interaction_at = workflow_now(datetime)
        live._schedule_next_action(db, conversation, lead, f'initial:{lead.id}')
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
