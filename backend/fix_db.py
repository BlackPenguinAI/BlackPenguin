from app.db.postgres import engine
# 🚀 Añadimos la importación de Company para que SQLAlchemy conozca la relación
from app.modules.tenants.models import Company
from app.modules.ai.models import AIConfiguration

print("🧹 Borrando la tabla vieja de configuración IA...")
AIConfiguration.__table__.drop(engine, checkfirst=True)

print("✨ Creando la nueva tabla Multi-Agente...")
AIConfiguration.__table__.create(engine, checkfirst=True)

print("🚀 ¡Tabla actualizada con éxito! Ya puedes borrar este script.")