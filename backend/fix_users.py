from app.db.postgres import engine
from sqlalchemy import text

# Lista de columnas nuevas que agregamos para el perfil
queries = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(150);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name_paternal VARCHAR(100);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name_maternal VARCHAR(100);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS document_type VARCHAR(20);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS document_number VARCHAR(50);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS birth_date DATE;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(50);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS country VARCHAR(100);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(100);",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS address VARCHAR(255);"
]

print("Iniciando actualización de la tabla 'users'...")

with engine.begin() as conn:
    for query in queries:
        try:
            conn.execute(text(query))
            print(f"✅ Éxito: {query.split('ADD COLUMN IF NOT EXISTS ')[1]}")
        except Exception as e:
            print(f"⚠️ Error al agregar: {e}")

print("🚀 ¡Migración de usuarios completada de forma segura!")