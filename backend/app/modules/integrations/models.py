from pydantic import BaseModel
from typing import List
from app.modules.ai.models import MongoChatMessage

class ConversationCreatePayload(BaseModel):
    lead_id: str
    agent_type: str
    messages: List[MongoChatMessage]
    total_tokens_used: int = 0

class InteractiveChatRequest(BaseModel):
    lead_id: str
    message: str

class InteractiveChatResponse(BaseModel):
    status: str
    response: str