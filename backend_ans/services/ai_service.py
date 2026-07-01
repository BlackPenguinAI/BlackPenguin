import httpx
from typing import List, Dict
from app.core.config import settings

class AIService:
    @staticmethod
    async def generate_response(messages: List[Dict[str, str]]) -> str:
        """
        Envía de forma asíncrona el historial de mensajes a OpenRouter 
        y devuelve la respuesta generada por el LLM (DeepSeek Chat por defecto).
        """
        url = "https://openrouter.ai/api/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://blackpenguin.ai", # Requerido por OpenRouter
            "X-Title": settings.PROJECT_NAME,         # Requerido por OpenRouter
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
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    return f"⚠️ Error de Comunicación con IA (Status: {response.status_code})"
            except Exception as e:
                return f"❌ Error Interno del Servidor de IA: {str(e)}"