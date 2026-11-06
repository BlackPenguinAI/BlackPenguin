"""Immutable UI receipts; never used as approved commercial facts."""
from copy import deepcopy
from datetime import datetime


def property_receipt(db, project, item, action, actor_id=None):
    from . import catalog_service, services
    from .models import SenderType, ProjectSession
    if not project.session:
        db.add(ProjectSession(project_id=project.id))
        db.flush(); db.refresh(project, ["session"])
    data = deepcopy(catalog_service.serialize(item))
    for key in ("created_at", "updated_at", "inventory_updated_at"):
        if hasattr(data.get(key), "isoformat"):
            data[key] = data[key].isoformat()
    services.save_message(
        db, project.session.id, SenderType.AI,
        f"Property type {action}: {item.name}. This receipt preserves this decision; later edits do not change it. Image association does not grant lead-sharing permission.",
        artifact_payload={"kind": "property_catalog_snapshot", "title": f"Property type {action}",
                          "confirmed_at": datetime.utcnow().isoformat(), "actor_user_id": actor_id,
                          "action": action, "items": [data]}, commit=False,
    )
