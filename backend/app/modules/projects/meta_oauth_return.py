"""OAuth auxiliary window bridge. Only a nonce and a safe result reach the opener."""
import html
import json
import secrets
from urllib.parse import urlsplit, urlencode
from fastapi.responses import HTMLResponse


def oauth_return(app_url: str, *, state: str, project_id: str | None, connected: bool, reason: str = "") -> HTMLResponse:
    app = urlsplit(app_url)
    origin = f"{app.scheme}://{app.netloc}"
    path = f"/app/projects/{project_id}/onboarding" if project_id else "/app/projects"
    fallback = origin + path + "?" + urlencode({"meta_oauth": "connected" if connected else "error", "reason": reason})
    payload = json.dumps({"type": "bp-meta-oauth", "state": state, "project_id": project_id,
        "status": "connected" if connected else "error", "reason": reason}).replace("<", "\\u003c")
    nonce = secrets.token_urlsafe(24)
    title = "Meta account connected" if connected else "Meta connection not completed"
    body = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="referrer" content="no-referrer">
<title>{title}</title><body><h1>{title}</h1>
<p>{html.escape(reason) if reason else 'Your authorization was saved. Return to onboarding to select this Project’s campaigns and forms.'}</p>
<p>You can close this window and continue in the original onboarding tab. If it is no longer open:</p>
<a href="{html.escape(fallback, quote=True)}" rel="noreferrer">Return to Project onboarding</a>
<script nonce="{nonce}">if(window.opener){{window.opener.postMessage({payload},{json.dumps(origin)});window.close();}}else{{window.location.replace({json.dumps(fallback)});}}</script></body></html>'''
    return HTMLResponse(body, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; base-uri 'none'; frame-ancestors 'none'"})
