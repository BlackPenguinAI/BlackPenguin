from sqlalchemy import Column, String, ForeignKey
import uuid
from app.db.postgres import Base

class Broker(Base):
    __tablename__ = "brokers"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(150), nullable=False)
    google_calendar_id = Column(String(255), nullable=True) # Para la sincronización