from datetime import datetime
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class ProjectUserAssignment(Base):
    __tablename__ = "project_user_assignments"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_user_assignment"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    responsibility = Column(String(30), nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    routing_weight = Column(Integer, default=100, nullable=False)
    accepts_new_leads = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User")
    project = relationship("Project")
