from app.db.postgres import engine
from sqlalchemy import text
from app.modules.tenants.models import SubscriptionPlan, Company
from app.modules.properties.models import Project

print("🧹 1/3 Borrando tablas antiguas de proyectos y empresas (forzando CASCADE)...")

# Usamos SQL nativo para forzar el borrado de relaciones dependientes
with engine.begin() as conn:
    conn.execute(text("DROP TABLE IF EXISTS projects CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS companies CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS subscription_plans CASCADE;"))

print("✨ 2/3 Recreando la nueva arquitectura Enterprise...")
# Recreamos las tablas limpias y con los nuevos campos
SubscriptionPlan.__table__.create(engine, checkfirst=True)
Company.__table__.create(engine, checkfirst=True)
Project.__table__.create(engine, checkfirst=True)

print("🚀 3/3 ¡Migración de base de datos exitosa! (Tu superadmin sigue intacto)")