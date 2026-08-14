from datetime import datetime

from sqlalchemy import Column, DateTime, String

from app.db.postgres import Base


CURRENT_SCHEMA_VERSION = "20260814_company_catalog_media"


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    version = Column(String(100), primary_key=True)
    applied_at = Column(DateTime, default=datetime.utcnow, nullable=False)
