import httpx
from typing import List, Dict
from app.core.config import settings

class AIService:
    @staticmethod
    async def generate_response(messages: List[Dict[str, str]]) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://blackpenguin.ai", 
            "X-Title": settings.PROJECT_NAME,
            "Content-Type": "application/json"
        }
        payload = {
            "model": settings.DEFAULT_AI_MODEL,
            "messages": messages,
            "temperature": 0.7
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=headers, json=payload, timeout=30.0)
                if response.status_code == 200:
                    return response.json()["choices"][0]["message"]["content"]
                return f"⚠️ Error IA ({response.status_code}): No se pudo contactar al LLM."
            except Exception as e:
                return f"❌ Error Servidor: {str(e)}"