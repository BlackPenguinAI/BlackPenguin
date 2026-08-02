import json
import logging

import httpx
from bs4 import BeautifulSoup

from app.db.postgres import SessionLocal
from app.integrations.openrouter_client import generate_llm_response
from app.modules.ai_core.services import get_ai_config

from . import services


logger = logging.getLogger(__name__)


async def scrape_and_enrich_profile(company_id: str, url: str) -> None:
    """Extract company facts from an authorized URL without confirming them."""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "BlackPenguinCompanyOnboarding/1.0"},
                timeout=15.0,
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.extract()
        text_content = soup.get_text(separator=" ", strip=True)[:15000]

        db = SessionLocal()
        try:
            config = get_ai_config(db, company_id=company_id)
            if not config.openrouter_api_key:
                logger.error("Company scraper has no OpenRouter key for company %s", company_id)
                return

            model = (config.agent_onboarding_empresa or {}).get("model", "openai/gpt-4o-mini")
            schema = {
                "updates": [
                    {
                        "field": "official_company_name",
                        "value": None,
                        "status": "extracted",
                        "applicable": None,
                        "source_type": "official_company_website",
                        "source_reference": url,
                        "confidence": "high",
                    }
                ]
            }
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Extract only company-level facts supported by the supplied page. "
                        "Return valid JSON only. Never mark a field confirmed. Use status extracted. "
                        "Allowed field keys are those in the Black Penguin Company Onboarding profile."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Expected shape: {json.dumps(schema)}\n"
                        f"Source URL: {url}\n"
                        f"Page text: {text_content}"
                    ),
                },
            ]
            raw = await generate_llm_response(config.openrouter_api_key, model, messages)
            clean = raw.replace("```json", "").replace("```", "").strip()
            payload = json.loads(clean)
            updates = payload.get("updates", []) if isinstance(payload, dict) else []

            profile = services.get_or_create_profile(db, company_id)
            services.apply_field_updates(
                db,
                profile,
                updates,
                allow_authoritative_statuses=False,
            )
        finally:
            db.close()
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.exception("Company website extraction failed for %s: %s", company_id, exc)
