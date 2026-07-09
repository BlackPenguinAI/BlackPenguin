# app/db/base.py
from app.db.postgres import Base  # Importa tu Base original aquí

# Importa todos tus modelos debajo
from app.modules.auth.models import User, UserRole
from app.modules.companies.models import Company
from app.modules.sales.models import WaitlistEmail, Lead