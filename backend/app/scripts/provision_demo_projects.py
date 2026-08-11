from app.db.postgres import SessionLocal
from app.modules.companies.models import Company
from app.modules.demo_projects.service import provision_demo_project
from app.modules.users.models import User, UserRole


def main() -> None:
    db = SessionLocal()
    try:
        created = 0
        for company in db.query(Company).all():
            admin = db.query(User).filter(
                User.company_id == company.id,
                User.role == UserRole.ADMIN,
            ).order_by(User.id.asc()).first()
            if not admin:
                print(f"Skipped {company.id}: no Company admin")
                continue
            provision_demo_project(db, company_id=company.id, approved_by_user_id=admin.id)
            created += 1
        db.commit()
        print(f"Provisioned or refreshed {created} Demo Projects")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
