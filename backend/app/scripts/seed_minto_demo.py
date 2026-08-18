from __future__ import annotations

import json
import os

from app.db.postgres import SessionLocal
from app.modules.demo_data.minto_seed import seed_minto_demo


def main() -> None:
    email = os.getenv("MINTO_DEMO_EMAIL", "test@minto.com")
    password = os.getenv("MINTO_DEMO_PASSWORD", "1234")
    db = SessionLocal()
    try:
        result = seed_minto_demo(db, email=email, password=password)
        print(json.dumps(result, indent=2))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
