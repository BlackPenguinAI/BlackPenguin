"""One malformed historical receipt must not stop another scope's recovery."""


def attempt(db, model, identifier, callback):
    try:
        from .dialogue_store import Scope, check_scope
        row = db.get(model, identifier)
        if not row:
            return
        check_scope(db, Scope(row.company_id, row.project_id, row.conversation_id, row.lead_id))
        callback()
    except (PermissionError, ValueError, KeyError, TypeError) as exc:
        db.rollback()
        row = db.get(model, identifier)
        if row and row.calendar_status not in {'synced','completed','simulation','cancelled'}:
            row.calendar_status = 'review'
            row.last_error = 'RecoveryReview:' + type(exc).__name__
            db.commit()
