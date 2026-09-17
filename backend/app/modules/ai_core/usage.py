from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Mapping

from sqlalchemy import func

from app.db.postgres import SessionLocal
from app.modules.companies.models import Company
from app.modules.users.models import User


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMUsageContext:
    """Tenant attribution carried alongside one provider request.

    ``user_id`` is intentionally optional: proactive sales-agent executions are
    company consumption but are not attributable to a signed-in user.
    """

    company_id: str
    user_id: str | None = None
    project_id: str | None = None
    feature: str = "unspecified"
    agent_run_event_id: str | None = None


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _non_negative_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def record_openrouter_usage(
    *, context: LLMUsageContext, model: str, response_id: str | None,
    usage: Mapping[str, Any],
) -> None:
    """Persist provider-reported totals without coupling them to caller commits."""

    prompt_tokens = _non_negative_int(usage.get("prompt_tokens"))
    completion_tokens = _non_negative_int(usage.get("completion_tokens"))
    total_tokens = _non_negative_int(usage.get("total_tokens"))
    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens
    cost = _non_negative_float(usage.get("cost"))
    if total_tokens == 0 and cost == 0:
        return

    db = SessionLocal()
    try:
        company_updated = db.query(Company).filter(Company.id == context.company_id).update({
            Company.ai_tokens_used: func.coalesce(Company.ai_tokens_used, 0) + total_tokens,
            Company.ai_cost_usd: func.coalesce(Company.ai_cost_usd, 0.0) + cost,
        }, synchronize_session=False)
        if not company_updated:
            logger.warning("llm_usage_company_missing company_id=%s", context.company_id)
            db.rollback()
            return

        if context.user_id:
            db.query(User).filter(
                User.id == context.user_id,
                User.company_id == context.company_id,
            ).update({
                User.ai_tokens_used: func.coalesce(User.ai_tokens_used, 0) + total_tokens,
                User.ai_cost_usd: func.coalesce(User.ai_cost_usd, 0.0) + cost,
            }, synchronize_session=False)

        if context.agent_run_event_id:
            # Imported lazily to keep model registration free of circular imports.
            from app.modules.sales_agent.models import AgentRun

            run = db.query(AgentRun).filter(
                AgentRun.event_id == context.agent_run_event_id,
            ).first()
            if run:
                previous = run.token_usage if isinstance(run.token_usage, dict) else {}
                run.token_usage = {
                    "prompt_tokens": _non_negative_int(previous.get("prompt_tokens")) + prompt_tokens,
                    "completion_tokens": _non_negative_int(previous.get("completion_tokens")) + completion_tokens,
                    "total_tokens": _non_negative_int(previous.get("total_tokens")) + total_tokens,
                    "cost": _non_negative_float(previous.get("cost")) + cost,
                    "provider": "openrouter",
                    "model": model,
                    "response_id": response_id,
                    "feature": context.feature,
                    "project_id": context.project_id,
                }
                run.estimated_cost_usd = f"{_non_negative_float(previous.get('cost')) + cost:.10f}"

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
