import httpx
import json
from bs4 import BeautifulSoup
from app.db.postgres import SessionLocal
from app.modules.company_onboarding.models import CompanyProfile
from app.modules.ai_core.services import get_ai_config
from app.integrations.openrouter_client import generate_llm_response

async def scrape_and_enrich_profile(company_id: str, url: str):
    """Extrae el texto de la URL y usa el LLM para enriquecer el perfil de forma silenciosa."""
    print(f"🕵️‍♂️ Iniciando escaneo profundo en: {url}")
    
    try:
        async with httpx.AsyncClient() as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            response = await client.get(str(url), headers=headers, timeout=15.0)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                for script in soup(["script", "style"]):
                    script.extract()
                text_content = soup.get_text(separator=' ', strip=True)[:15000]
                
                db = SessionLocal()
                try:
                    config = get_ai_config(db, company_id=company_id)
                    ai_key = config.openrouter_api_key
                    model = config.agent_onboarding_empresa.get("model", "openai/gpt-4o-mini")
                    
                    if not ai_key:
                        print("❌ Extractor: No hay API Key configurada.")
                        return

                    messages = [
                        {"role": "system", "content": "Eres un extractor de datos JSON estricto. Responde ÚNICAMENTE con el JSON, sin markdown, sin texto extra."},
                        {"role": "user", "content": "Extrae los datos de esta empresa en el siguiente formato JSON exacto, si no encuentras algo déjalo nulo o vacío: {{\"legal_name\": \"\", \"dba\": \"\", \"headquarters\": \"\", \"year_established\": \"\", \"executive_team\": [\"{name\": \"\", \"role\": \"\"}], \"asset_classes\": [], \"market_coverage\": \"\", \"target_demographics\": \"\", \"aum\": \"\", \"investment_strategy\": \"\", \"value_proposition\": \"\", \"key_differentiators\": \"\", \"tone_of_voice\": \"\", \"key_messaging\": \"\"}}. TEXTO WEB: {text_content}"}
                    ]
                    
                    llm_response = await generate_llm_response(ai_key, model, messages)
                    
                    try:
                        clean_json = llm_response.replace('```json', '').replace('```', '').strip()
                        extracted_data = json.loads(clean_json)
                        
                        profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).first()
                        if not profile:
                            profile = CompanyProfile(company_id=company_id)
                            db.add(profile)
                            
                        for key, value in extracted_data.items():
                            if value and getattr(profile, key) in [None, "", []]:
                                setattr(profile, key, value)
                                
                        profile.is_identity_completed = bool(profile.legal_name and profile.headquarters)
                        profile.is_team_completed = bool(len(profile.executive_team) > 0)
                        profile.is_focus_completed = bool(len(profile.asset_classes) > 0)
                        profile.is_market_completed = bool(profile.market_coverage)
                        profile.is_strategy_completed = bool(profile.investment_strategy)
                        profile.is_value_prop_completed = bool(profile.value_proposition)
                        profile.is_brand_completed = bool(profile.tone_of_voice and profile.key_messaging)
                        
                        profile.is_profile_fully_completed = all([
                            profile.is_identity_completed, profile.is_team_completed, profile.is_focus_completed, 
                            profile.is_market_completed, profile.is_strategy_completed, profile.is_value_prop_completed, 
                            profile.is_brand_completed
                        ])
                        db.commit()
                        print(f"✨ WOW EFFECT COMPLETADO: Perfil {company_id} actualizado.")
                    except json.JSONDecodeError:
                        print("❌ Error parseando JSON del LLM.")
                finally:
                    db.close()
            else:
                print(f"❌ Extractor Silencioso: Error HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ Error en la extracción silenciosa: {e}")