import httpx
import urllib.request
import json
from typing import List, Dict

async def generate_llm_response(api_key: str, model: str, messages: List[Dict[str, str]], app_name: str = "Black Penguin") -> str:
    """Envía la solicitud asíncrona al LLM para generar texto."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://blackpenguin.ai", 
        "X-Title": app_name,
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
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

def check_openrouter_consumption(api_key: str) -> dict:
    """Consulta síncrona para obtener el saldo y límite de la API Key."""
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key", 
            headers={"Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            key_data = data.get("data", {})
            return {
                "usage": key_data.get("usage", 0),
                "limit": key_data.get("limit", 0),
                "label": key_data.get("label", "OpenRouter Key")
            }
    except Exception as e:
        return {"usage": 0, "limit": 0, "error": str(e)}