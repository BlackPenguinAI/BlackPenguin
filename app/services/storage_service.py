import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile, HTTPException
from app.core.config import settings
import uuid

class SpaceStorageServiceV2:
    def __init__(self):
        # Configuración del cliente Boto3
        self.session = boto3.session.Session()
        self.client = self.session.client(
            's3',
            region_name=settings.DO_SPACES_REGION,
            endpoint_url=f"https://{settings.DO_SPACES_REGION}.digitaloceanspaces.com",
            aws_access_key_id=settings.DO_SPACES_KEY,
            aws_secret_access_key=settings.DO_SPACES_SECRET
        )
        self.bucket_name = settings.DO_SPACES_BUCKET

    async def upload_public_asset(self, company_id: str, project_id: str, file: UploadFile, asset_type: str) -> str:
        """
        Sube recursos de marketing (brochures, renders, tours v2.0)
        con permisos públicos para ser enviados por el chatbot.
        """
        safe_filename = f"{uuid.uuid4().hex}_{file.filename.replace(' ', '_')}"
        object_key = f"tenants/{company_id}/projects/{project_id}/{asset_type}/{safe_filename}"

        try:
            self.client.upload_fileobj(
                file.file,
                self.bucket_name,
                object_key,
                ExtraArgs={"ACL": "public-read", "ContentType": file.content_type}
            )
            return f"https://{self.bucket_name}.{settings.DO_SPACES_REGION}.digitaloceanspaces.com/{object_key}"
        except ClientError as e:
            raise HTTPException(status_code=500, detail="Error subiendo activo público a Spaces.")

    async def upload_voice_recording(self, company_id: str, lead_id: str, file: UploadFile) -> str:
        """
        [NUEVO V2.0] Sube la grabación de una llamada generada por el Agente de Voz.
        Este archivo se marca como PRIVADO por estricto cumplimiento legal (Compliance).
        """
        safe_filename = f"call_{uuid.uuid4().hex}.mp3"
        object_key = f"tenants/{company_id}/leads/{lead_id}/voice_recordings/{safe_filename}"

        try:
            self.client.upload_fileobj(
                file.file,
                self.bucket_name,
                object_key,
                ExtraArgs={"ACL": "private", "ContentType": "audio/mpeg"}
            )
            # Retorna el Object Key (ruta interna) para guardarlo en la metadata de MongoDB
            return object_key 
        except ClientError as e:
            raise HTTPException(status_code=500, detail="Error guardando grabación de voz.")

    def generate_presigned_url(self, object_key: str, expiration_seconds: int = 3600) -> str:
        """
        [NUEVO V2.0] Genera una URL temporal segura. 
        Se usa cuando el rol 'Sales' presiona "Escuchar Llamada" en el Dashboard.
        """
        try:
            response = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_key},
                ExpiresIn=expiration_seconds
            )
            return response
        except ClientError as e:
            raise HTTPException(status_code=500, detail="No se pudo generar el enlace seguro de audio.")

# Instancia global inyectable
storage_service = SpaceStorageServiceV2()