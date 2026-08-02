"""Safely update only the existing Company Onboarding prompts."""

from sqlalchemy.orm.attributes import flag_modified

from app.db.postgres import SessionLocal
from app.modules.ai_core.models import AIConfiguration
from app.modules.company_onboarding.prompts import COMPANY_ONBOARDING_AGENT_CONFIG


def update_prompts() -> int:
    db = SessionLocal()
    try:
        configs = db.query(AIConfiguration).all()
        for config in configs:
            current = dict(config.agent_onboarding_empresa or {})
            current.update(COMPANY_ONBOARDING_AGENT_CONFIG)
            config.agent_onboarding_empresa = current
            flag_modified(config, "agent_onboarding_empresa")
        db.commit()
        return len(configs)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print(f"Updated {update_prompts()} Company Onboarding configuration(s).")
