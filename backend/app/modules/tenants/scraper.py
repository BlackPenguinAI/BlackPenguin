import httpx
import json
from bs4 import BeautifulSoup
from app.db.postgres import SessionLocal
from app.modules.tenants.models import CompanyProfile
from app.core.config import settings

async def scrape_and_enrich_profile(company_id: str, url: str):
    """
    Background Task: Visita la URL, extrae el texto, lo pasa por el LLM 
    y guarda el JSON resultante en el perfil cognitivo de la empresa.
    """
    print(f"🕵️‍♂️ Iniciando escaneo profundo en: {url}")
    
    # 1. Extraer texto de la web
    try:
        async with httpx.AsyncClient() as client:
            # Nos hacemos pasar por un navegador real para que no nos bloqueen
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            response = await client.get(url, headers=headers, timeout=15.0)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Extraemos solo el texto visible, eliminando scripts y estilos
                for script in soup(["script", "style"]):
                    script.extract()
                text_content = soup.get_text(separator=' ', strip=True)
                # Recortamos a 15,000 caracteres para no saturar al LLM
                text_content = text_content[:15000]
            else:
                print(f"⚠️ Error {response.status_code} al escanear la URL.")
                return
    except Exception as e:
        print(f"❌ Error durante el Web Scraping: {e}")
        return

    # 2. Pedirle a la IA que estructure el texto en JSON
    prompt = f"""
    Eres un analista de datos de Black Penguin. Lee el siguiente texto extraído del sitio web de una constructora/desarrolladora inmobiliaria y extrae la información en un formato JSON estricto. 
    Si no encuentras un dato, déjalo como null o lista vacía [].
    NO agregues texto fuera del JSON (ni siquiera formato markdown ```json). Solo devuelve el JSON puro.
    
    FORMATO JSON REQUERIDO:
    {{
        "legal_name": "Nombre de la empresa",
        "dba": "Nombre comercial",
        "headquarters": "Sede principal",
        "year_established": 2000,
        "executive_team": [{{"name": "Juan Perez", "role": "CEO"}}],
        "asset_classes": ["Multi-family", "Commercial"],
        "core_focus_description": "Breve resumen de enfoque",
        "market_coverage": "Zonas o estados donde operan",
        "target_demographics": "A quién le venden",
        "portfolio_size_aum": "Tamaño del portafolio si se menciona",
        "investment_strategy": "Estrategia de inversión",
        "value_proposition": "Propuesta de valor",
        "key_differentiators": "Diferenciadores clave",
        "tone_of_voice": "Tono de la marca (ej: Corporativo, Lujo)",
        "key_messaging": "Mensaje principal"
    }}
    
    TEXTO DE LA WEB:
    {text_content}
    """

    try:
        async with httpx.AsyncClient() as client:
            ai_body = {
                "model": settings.DEFAULT_AI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1
            }
            
            # EL ENLACE CORREGIDO, SIN FORMATOS DE MARKDOWN
            ai_response = await client.post(
                "[https://openrouter.ai/api/v1/chat/completions](https://openrouter.ai/api/v1/chat/completions)",
                headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                json=ai_body, 
                timeout=40.0
            )
            
            if ai_response.status_code == 200:
                ai_text = ai_response.json()["choices"][0]["message"]["content"].strip()
                
                # Limpiamos si el LLM terco mandó markdown
                if ai_text.startswith("```json"): 
                    ai_text = ai_text[7:]
                if ai_text.endswith("```"): 
                    ai_text = ai_text[:-3]
                
                try:
                    extracted_data = json.loads(ai_text)
                except json.JSONDecodeError:
                    print("❌ Error: La respuesta de la IA no es un JSON válido.")
                    print(ai_text)
                    return
                
                # 3. Guardar en Base de Datos de forma asíncrona pero segura
                db = SessionLocal()
                try:
                    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).first()
                    if profile:
                        # Rellenar datos dinámicamente
                        for key, value in extracted_data.items():
                            if hasattr(profile, key) and value:
                                setattr(profile, key, value)
                        
                        # Actualizar banderas de compleción automáticamente
                        profile.is_identity_completed = bool(profile.legal_name and profile.headquarters)
                        profile.is_team_completed = bool(len(profile.executive_team) > 0)
                        profile.is_focus_completed = bool(len(profile.asset_classes) > 0)
                        profile.is_market_completed = bool(profile.market_coverage)
                        profile.is_strategy_completed = bool(profile.investment_strategy)
                        profile.is_value_prop_completed = bool(profile.value_proposition)
                        profile.is_brand_completed = bool(profile.tone_of_voice and profile.key_messaging)
                        
                        db.commit()
                        print(f"✨ WOW EFFECT COMPLETADO: Perfil de {company_id} enriquecido con IA.")
                finally:
                    db.close()
            else:
                print(f"❌ Error en OpenRouter al procesar el Scrape. Status: {ai_response.status_code}")
    except Exception as e:
        print(f"❌ Error en la extracción LLM o Base de Datos: {e}")