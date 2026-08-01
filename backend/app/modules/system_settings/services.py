from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import FirebaseConfig, TwilioConfig, LegalDocument
from .schemas import FirebaseConfigUpdate, TwilioConfigUpdate, LegalDocumentPayload

# --- FIREBASE ---
def get_firebase_config(db: Session) -> FirebaseConfig:
    config = db.query(FirebaseConfig).first()
    if not config:
        config = FirebaseConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

def update_firebase_config(db: Session, payload: FirebaseConfigUpdate) -> FirebaseConfig:
    config = get_firebase_config(db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    db.commit()
    db.refresh(config)
    return config

# --- TWILIO ---
def get_twilio_config(db: Session) -> TwilioConfig:
    config = db.query(TwilioConfig).first()
    if not config:
        config = TwilioConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

def update_twilio_config(db: Session, payload: TwilioConfigUpdate) -> TwilioConfig:
    config = get_twilio_config(db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    db.commit()
    db.refresh(config)
    return config

# --- LEGAL ---
def get_legal_document(db: Session, doc_type: str, lang: str = "en") -> LegalDocument:
    document = db.query(LegalDocument).filter(
        LegalDocument.doc_type == doc_type,
        LegalDocument.language == lang
    ).first()
    
    if not document:
        document = LegalDocument(
            doc_type=doc_type,
            language=lang,
            last_updated_label="July 2026" if lang == "en" else "Julio 2026",
            content_markdown=f"# {doc_type.capitalize()} Policy\n\n*Content under construction.*"
        )
        db.add(document)
        db.commit()
        db.refresh(document)
    return document

def update_legal_document(db: Session, doc_type: str, payload: LegalDocumentPayload, lang: str = "en") -> LegalDocument:
    if doc_type not in ["privacy", "terms"]:
        raise HTTPException(status_code=400, detail="Documento legal inválido.")
        
    document = db.query(LegalDocument).filter(
        LegalDocument.doc_type == doc_type,
        LegalDocument.language == lang
    ).first()
    
    if not document:
        document = LegalDocument(
            doc_type=doc_type,
            language=lang,
            content_markdown=payload.content_markdown,
            last_updated_label=payload.last_updated_label
        )
        db.add(document)
    else:
        document.content_markdown = payload.content_markdown
        document.last_updated_label = payload.last_updated_label
        
    db.commit()
    db.refresh(document)
    return document