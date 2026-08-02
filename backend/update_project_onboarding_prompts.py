"""Safely update Project Onboarding prompts without running destructive init_db.py."""

from sqlalchemy.orm.attributes import flag_modified

from app.db.postgres import SessionLocal
from app.modules.ai_core.models import AIConfiguration
from app.modules.projects.prompts import PROJECT_ONBOARDING_AGENT_CONFIG, SALES_AGENT_CONFIG


def update_prompts() -> int:
    db = SessionLocal()
    try:
        configs = db.query(AIConfiguration).all()
        for config in configs:
            project = dict(config.agent_onboarding_proyectos or {})
            project.update(PROJECT_ONBOARDING_AGENT_CONFIG)
            config.agent_onboarding_proyectos = project
            sales = dict(config.agent_ventas or {})
            sales.update(SALES_AGENT_CONFIG)
            config.agent_ventas = sales
            flag_modified(config, "agent_onboarding_proyectos")
            flag_modified(config, "agent_ventas")
        db.commit()
        return len(configs)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print(f"Updated {update_prompts()} Project Onboarding and Sales configuration(s).")
