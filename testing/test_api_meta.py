# Instala la librería si no la tienes: pip install requests
import requests
import json

# ==========================================
# CREDENCIALES DE META (Graph API)
# ==========================================
ACCESS_TOKEN = "EAAVNB23QOsgBRZCTCzjHZBEbsEg2IOnViXjJcTqsxSIuZAaYyS2dQmPqZClTzi8Mxc9Uj61XmCuMDZALyYZAVbMe4M3ogqBhh9IgWHqDrY6sc5aPziDANAZAp9tGC2fSY6dlcciVogqWnMhAaWRupZA66HrossFHoZBDGxwcbZBE89gqZAVxF1Vcb0b1A6zFVNUufjMNQZDZD"
AD_ACCOUNT_ID = "act_1053799847811121"
#AD_ACCOUNT_ID = "act_2085805425529941" # Cuenta publicitaria
API_VERSION = "v20.0"

def get_meta_campaigns():
    """Obtiene la lista de campañas de la cuenta publicitaria."""
    url = f"https://graph.facebook.com/{API_VERSION}/{AD_ACCOUNT_ID}/campaigns"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,status,objective",
        "limit": 10
    }
    
    print(f"🚀 Conectando a Meta Graph API ({API_VERSION}) para obtener campañas...")
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        print(f"❌ Error al obtener campañas: {json.dumps(response.json(), indent=2)}")
        return []
        
    return response.json().get("data", [])

def get_leads_from_campaign(campaign_id):
    """Extrae los leads (clientes potenciales) de una campaña específica."""
    url = f"https://graph.facebook.com/{API_VERSION}/{campaign_id}/leads"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,created_time,field_data",
        "limit": 5  # Extraemos los 5 más recientes para probar
    }
    
    response = requests.get(url, params=params)
    
    if response.status_code != 200:
        print(f"      ❌ Error al obtener leads: {json.dumps(response.json(), indent=2)}")
        return []
        
    return response.json().get("data", [])

if __name__ == "__main__":
    print("-" * 50)
    # 1. Obtenemos las campañas
    campaigns = get_meta_campaigns()
    
    if not campaigns:
        print("⚠️ No se encontraron campañas.")
    else:
        print(f"✅ ¡Se encontraron {len(campaigns)} campañas! Buscando prospectos...\n")
        
        # 2. Iteramos por cada campaña y extraemos sus leads
        for camp in campaigns:
            print(f"📊 Campaña: {camp.get('name')} (ID: {camp.get('id')})")
            
            # Llamamos a la API para ver si esta campaña tiene leads
            leads = get_leads_from_campaign(camp.get('id'))
            
            if not leads:
                print("   ⚠️ No hay prospectos registrados aquí aún.\n")
            else:
                print(f"   🐧 ¡Se encontraron {len(leads)} prospectos! Extrayendo materia prima:")
                for lead in leads:
                    print(f"      🆔 Lead ID: {lead.get('id')} | 📅 Fecha: {lead.get('created_time')}")
                    
                    # Extraemos y formateamos las respuestas del formulario
                    for field in lead.get('field_data', []):
                        question = field['name']
                        # Si el usuario dejó el campo vacío, mostramos 'N/A'
                        answer = field['values'][0] if field['values'] else 'N/A'
                        print(f"         -> {question}: {answer}")
                print("   " + "-" * 40 + "\n")