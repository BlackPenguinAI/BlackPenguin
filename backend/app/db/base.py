# app/db/base.py
from app.db.postgres import Base  # Importa tu Base original aquí

# Importa todos tus modelos debajo
from app.modules.ai.models import *
from app.modules.auth.models import *
from app.modules.integrations.models import *
from app.modules.properties.models import *
from app.modules.sales.models import *
from app.modules.tenants.models import *