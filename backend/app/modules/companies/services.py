import os
import shutil
from fastapi import UploadFile
from datetime import datetime

UPLOAD_DIR = "uploads/receipts"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def save_receipt_file(email: str, file: UploadFile) -> str:
    """Guarda el comprobante localmente y devuelve la URL."""
    file_ext = file.filename.split(".")[-1]
    new_filename = f"{email.split('@')[0]}_{int(datetime.utcnow().timestamp())}.{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, new_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return f"/uploads/receipts/{new_filename}"