from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.base import Base
from app.db.postgres import SessionLocal, engine
from app.modules.users.models import User, UserRole


def seed_local_user() -> None:
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == settings.FIRST_SUPERADMIN_EMAIL).first()

        if user:
            user.hashed_password = get_password_hash(settings.FIRST_SUPERADMIN_PASSWORD)
            user.role = UserRole.SUPERADMIN
            user.is_active = True
            user.company_id = None
            if not user.first_name:
                user.first_name = "Local"
            db.commit()
            print(f"Updated local superadmin: {settings.FIRST_SUPERADMIN_EMAIL}")
            return

        user = User(
            email=settings.FIRST_SUPERADMIN_EMAIL,
            hashed_password=get_password_hash(settings.FIRST_SUPERADMIN_PASSWORD),
            role=UserRole.SUPERADMIN,
            is_active=True,
            first_name="Local",
        )
        db.add(user)
        db.commit()
        print(f"Created local superadmin: {settings.FIRST_SUPERADMIN_EMAIL}")
    except SQLAlchemyError as exc:
        db.rollback()
        raise SystemExit(f"Failed to seed local user: {exc}") from exc
    finally:
        db.close()


if __name__ == "__main__":
    seed_local_user()
