"""Safely update only the stored Company Onboarding prompt configuration.

Run this from the backend directory after replacing app/init_db.py. Unlike
init_db.py, this script does not drop schemas, create tables, or modify profiles.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.db.postgres import SessionLocal
from app.modules.ai_core.models import AIConfiguration


def read_default_agent_config() -> dict[str, Any]:
    init_db_path = Path(__file__).resolve().parent / "app" / "init_db.py"
    tree = ast.parse(init_db_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "ai_config"
                and target.attr == "agent_onboarding_empresa"
            ):
                value = ast.literal_eval(node.value)
                if isinstance(value, dict):
                    return value

    raise RuntimeError("Company Onboarding prompt configuration was not found in app/init_db.py")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--company-id",
        help="Update a company-specific AI configuration instead of the global default.",
    )
    args = parser.parse_args()

    prompt_config = read_default_agent_config()
    db = SessionLocal()
    try:
        query = db.query(AIConfiguration)
        if args.company_id:
            query = query.filter(AIConfiguration.company_id == args.company_id)
        else:
            query = query.filter(AIConfiguration.company_id.is_(None))

        ai_config = query.first()
        if ai_config is None:
            target = f"company {args.company_id}" if args.company_id else "global default"
            raise RuntimeError(f"No AI configuration exists for {target}.")

        ai_config.agent_onboarding_empresa = prompt_config
        flag_modified(ai_config, "agent_onboarding_empresa")
        db.commit()
        print("Company Onboarding prompts updated successfully.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
