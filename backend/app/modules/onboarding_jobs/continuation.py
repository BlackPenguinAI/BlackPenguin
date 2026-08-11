from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.onboarding_questions import build_next_question

from .models import OnboardingSourceJob


def _source_value(source: Any, attribute: str) -> str:
    value = getattr(source, attribute, "")
    return value.value if hasattr(value, "value") else str(value or "")


def _result_content(
    sources: list[Any], *, pending_count: int, question_prompt: str,
) -> str:
    failed = [source for source in sources if _source_value(source, "status") == "failed"]
    ready = [source for source in sources if _source_value(source, "status") == "ready"]
    parts: list[str] = []

    if failed:
        details = [
            f"- **{source.name}:** {source.error_message or 'The source could not be processed.'}"
            for source in failed[:5]
        ]
        if len(failed) > 5:
            details.append(f"- {len(failed) - 5} additional source(s) could not be processed.")
        parts.append("I couldn't analyze some of the sources you shared:\n\n" + "\n".join(details))

    if pending_count:
        parts.append(
            f"I extracted {pending_count} proposal{'s' if pending_count != 1 else ''} "
            "from the accessible sources. Review them before we continue."
        )
    else:
        if ready:
            parts.append(
                f"I finished processing {len(ready)} accessible "
                f"source{'s' if len(ready) != 1 else ''}."
            )
        elif failed:
            parts.append(
                "You can upload accessible copies later or provide the information manually."
            )
        parts.append(f"Let's continue: {question_prompt}")

    return "\n\n".join(parts)


def finalize_source_group(
    db: Session,
    *,
    scope: str,
    company_id: str,
    message_id: str | None,
    project_id: str | None = None,
):
    """Finish one source group exactly once after every sibling has settled."""

    if not message_id:
        return None
    active_job = db.query(OnboardingSourceJob).filter(
        OnboardingSourceJob.scope == scope,
        OnboardingSourceJob.message_id == message_id,
        OnboardingSourceJob.status.in_(["queued", "processing"]),
    ).first()
    if active_job:
        return None

    if scope == "company":
        from app.modules.company_onboarding import services
        from app.modules.company_onboarding.models import (
            CompanyOnboardingSource,
            OnboardingMessage,
            OnboardingSession,
            ProposalStatus,
            SenderType,
        )

        origin = db.query(OnboardingMessage).filter(
            OnboardingMessage.id == message_id,
        ).first()
        if not origin:
            return None
        db.query(OnboardingSession).filter(
            OnboardingSession.id == origin.session_id,
        ).with_for_update().one()
        sources = db.query(CompanyOnboardingSource).filter(
            CompanyOnboardingSource.company_id == company_id,
            CompanyOnboardingSource.message_id == message_id,
        ).all()
        profile = services.get_or_create_profile(db, company_id)
        blockers = services.serialize_profile(profile)["completion"]["blockers"]
        final_prompt = "Review the Company Profile and choose whether to approve it or make changes."
        pending_value = ProposalStatus.PENDING
        message_model = OnboardingMessage
        save_message = services.save_message
    elif scope == "project":
        from app.modules.projects import services
        from app.modules.projects.models import (
            ProjectMessage,
            ProjectOnboardingSource,
            ProjectProposalStatus,
            ProjectSession,
            SenderType,
        )

        project = services.get_project(db, project_id or "", company_id)
        origin = db.query(ProjectMessage).filter(ProjectMessage.id == message_id).first()
        if not origin:
            return None
        db.query(ProjectSession).filter(
            ProjectSession.id == origin.session_id,
        ).with_for_update().one()
        sources = db.query(ProjectOnboardingSource).filter(
            ProjectOnboardingSource.project_id == project.id,
            ProjectOnboardingSource.message_id == message_id,
        ).all()
        profile = services.get_profile(project)
        blockers = services.serialize_profile(profile)["completion"]["blockers"]
        final_prompt = "Review the Project Profile and choose whether to approve it or make changes."
        pending_value = ProjectProposalStatus.PENDING
        message_model = ProjectMessage
        save_message = services.save_message
    else:
        raise ValueError("unknown_scope")

    if not sources or any(_source_value(source, "status") == "processing" for source in sources):
        return None

    pending_count = sum(
        1
        for source in sources
        for proposal in source.proposals
        if proposal.status == pending_value
    )
    question = build_next_question(blockers, final_prompt=final_prompt)
    content = _result_content(
        sources,
        pending_count=pending_count,
        question_prompt=question["prompt"],
    )
    ui_payload = None if pending_count else question

    existing = db.query(message_model).filter(
        message_model.session_id == origin.session_id,
        message_model.sender == SenderType.AI,
        message_model.in_reply_to_message_id == origin.id,
        message_model.response_payload.is_(None),
    ).order_by(message_model.created_at.desc()).first()
    if existing:
        existing.content = content
        existing.ui_payload = ui_payload
        db.add(existing)
        db.flush()
        return existing
    return save_message(
        db,
        origin.session_id,
        SenderType.AI,
        content,
        ui_payload=ui_payload,
        in_reply_to_message_id=origin.id,
        commit=False,
    )
