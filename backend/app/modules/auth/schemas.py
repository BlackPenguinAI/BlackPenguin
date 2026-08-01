from pydantic import BaseModel

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    name: str