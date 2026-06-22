import requests
import json

ACCESS_TOKEN = "EAAVNB23QOsgBR4bx4ZBZBVSsFlSxxZBoTeZAf4mCZBwuBMCotnw21XUa2GOMu4mELDGdSaPH4ME0lpjpgJXXRtX2ocXeJs7TsURI0qQZBQS3XDQxdNCt3f9cAuN8x0hqEFZBnwTOL4nCjg6UWt0SRoITFr9nhVgjRptr8T1DtQJLBmNU8NLWrcp01V8YaXjQYmwYwZDZD"
API_VERSION = "v20.0"

def diagnosticar_robot():
    print("-" * 50)
    print("🕵️‍♂️ Radiografiando el Token de Meta...\n")
    
    # 1. Ver qué permisos tiene realmente grabados el token
    url_perms = f"https://graph.facebook.com/{API_VERSION}/me/permissions"
    res_perms = requests.get(url_perms, params={"access_token": ACCESS_TOKEN})
    
    if res_perms.status_code == 200:
        permisos = [p['permission'] for p in res_perms.json().get('data', []) if p['status'] == 'granted']
        print("📋 Permisos instalados en tu Token:")
        for p in permisos:
            print(f"  ✅ {p}")
        
        if 'leads_retrieval' not in permisos:
            print("\n❌ ¡ALERTA CRÍTICA! Tu token NO tiene el permiso 'leads_retrieval'.")
            print("👉 Solución: Vuelve a generar el token en Business Manager marcando la casilla.")
        else:
            print("\n✅ El permiso 'leads_retrieval' está instalado correctamente.")
    else:
        print(f"❌ Error al leer permisos: {res_perms.json()}")

    print("\n" + "-" * 50 + "\n")

    # 2. Ver a qué páginas de Facebook tiene acceso el robot
    url_pages = f"https://graph.facebook.com/{API_VERSION}/me/accounts"
    res_pages = requests.get(url_pages, params={"access_token": ACCESS_TOKEN})
    
    if res_pages.status_code == 200:
        paginas = res_pages.json().get('data', [])
        print(f"🏢 Tu robot tiene acceso a {len(paginas)} página(s) de Facebook:")
        for page in paginas:
            print(f"  ✅ {page['name']} (ID: {page['id']})")
            
        if len(paginas) == 0:
            print("\n❌ ¡ALERTA CRÍTICA! Tu robot no tiene acceso a la página GHL Golf.")
            print("👉 Solución: Ve al Business Manager > Cuentas > Páginas > Agrega a tu Usuario del Sistema.")
    else:
        print(f"❌ Error al leer páginas: {res_pages.json()}")
        
    print("-" * 50)

if __name__ == "__main__":
    diagnosticar_robot()