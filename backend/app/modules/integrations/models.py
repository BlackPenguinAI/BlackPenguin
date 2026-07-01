from sqlalchemy import Column, String, ForeignKey
import uuid
from app.db.postgres import Base

class MetaFormMapping(Base):
    __tablename__ = "meta_form_mappings"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    form_id = Column(String(100), unique=True, nullable=False)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)