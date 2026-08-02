import json
from typing import Any, Dict, List
import urllib.request

import httpx

async def generate_llm_response(
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    app_name: str = "Black Penguin",
    *,
    response_format: dict[str, Any] | None = None,
    temperature: float = 0.3,
    raise_on_error: bool = False,
) -> str:
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
        "temperature": temperature,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=45.0)
            response.raise_for_status()
            try:
                content = response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("OpenRouter returned an unexpected response.") from exc
            if not isinstance(content, str) or not content.strip():
                raise ValueError("OpenRouter returned an empty response.")
            return content
    except (httpx.HTTPError, ValueError) as exc:
        if raise_on_error:
            raise
        return f"⚠️ AI service unavailable: {exc}"

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
