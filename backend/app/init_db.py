import os
from sqlalchemy.orm import Session
from app.db.postgres import engine, Base, SessionLocal

# 🚀 IMPORTANTE: Importa todos tus modelos aquí para que SQLAlchemy sepa que existen
from app.modules.auth.models import User, UserRole
from app.modules.sales.models import WaitlistEmail, Lead
from app.core.security import get_password_hash # Tu función para encriptar contraseñas

def init_db():
    # 1. Crear todas las tablas que falten en la base de datos
    print("🔄 Verificando tablas en la base de datos...")
    Base.metadata.create_all(bind=engine)

    # 2. Sembrar el Superadmin de forma segura
    db: Session = SessionLocal()
    try:
        sa_email = os.getenv("FIRST_SUPERADMIN_EMAIL")
        sa_pass = os.getenv("FIRST_SUPERADMIN_PASSWORD")

        if sa_email and sa_pass:
            # Revisamos si ya existe alguien con ese correo
            existing_sa = db.query(User).filter(User.email == sa_email).first()
            
            if not existing_sa:
                print(f"🌱 Sembrando Superadmin por defecto: {sa_email}")
                superadmin = User(
                    email=sa_email,
                    hashed_password=get_password_hash(sa_pass),
                    role=UserRole.SUPERADMIN,
                    is_active=True
                )
                db.add(superadmin)
                db.commit()
            else:
                print("✅ El Superadmin ya existe. Omitiendo creación.")
        else:
            print("⚠️ Variables de entorno del Superadmin no encontradas.")
    except Exception as e:
        print(f"❌ Error durante el Data Seeding: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("🚀 Iniciando el proceso de Data Seeding...")
    init_db()
    print("✨ Proceso completado exitosamente.")