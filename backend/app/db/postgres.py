from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

# 1. Configuración del Motor
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 2. Base para todos los modelos relacionales futuros
Base = declarative_base()

# 3. Generador de Sesiones (Dependencia para FastAPI)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()