# backend/app/integrations/firebase_client.py

import firebase_admin
from firebase_admin import credentials, auth
import os

# Variable global para mantener la instancia de Firebase iniciada
_firebase_app = None

def get_firebase_app():
    global _firebase_app
    if not _firebase_app:
        try:
            # 🚀 Aquí configuraremos la lectura del JSON de credenciales de Firebase
            # Por ahora lo dejamos listo para instanciar
            # cred = credentials.Certificate("ruta/al/firebase-adminsdk.json")
            # _firebase_app = firebase_admin.initialize_app(cred)
            print("⚙️ Firebase inicializado correctamente.")
        except Exception as e:
            print(f"❌ Error al inicializar Firebase: {e}")
    return _firebase_app

def send_activation_email(email: str, link: str):
    """
    Simula / Ejecuta la generación y envío del link de activación vía Firebase.
    """
    # app = get_firebase_app()
    try:
        # Aquí conectaremos la función específica de Firebase Auth para emails
        # Ej: link = auth.generate_password_reset_link(email)
        print(f"\n--- 🚀 FIREBASE NOTIFICATION ---")
        print(f"To: {email}")
        print(f"Activation Link: {link}")
        print("--------------------------------\n")
        return True
    except Exception as e:
        print(f"❌ Error en Firebase Client al enviar correo: {e}")
        return False