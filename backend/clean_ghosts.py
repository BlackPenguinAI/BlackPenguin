from app.db.postgres import engine
from sqlalchemy import text

print("Iniciando limpieza de usuarios fantasmas...")

with engine.begin() as conn:
    # Usamos ::text para que PostgreSQL entienda la comparación con el ENUM
    conn.execute(text("DELETE FROM users WHERE role::text != 'superadmin';"))

print("👻 ¡Fantasmas eliminados! La base de datos está limpia.")