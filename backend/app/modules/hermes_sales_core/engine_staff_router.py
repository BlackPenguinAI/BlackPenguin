"""Staff-only Sales Agent selection API. No inference or business side effects."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from . import staff_config
from .engine_selection import EngineSelectionError, EngineUnavailable

router = APIRouter(prefix='/hermes', tags=['Hermes Staff Control'])
staff_only = RoleChecker([UserRole.SUPERADMIN])


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active_sales_engine: Literal['hermes', 'langgraph']
    change_note: str = Field(min_length=1, max_length=400)
    # Optional for older clients; HEI-05 sends both snapshot fields.
    expected_revision: int | None = Field(default=None, ge=0, strict=True)
    expected_published_version_id: str | None = Field(default=None, max_length=36)


def no_cache(response: Response) -> None:
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'


@router.get('/engine', dependencies=[Depends(no_cache)])
def get_engine(db: Session = Depends(get_db), actor: User = Depends(staff_only)):
    return staff_config.admin_engine_status(db)


@router.put('/engine', dependencies=[Depends(no_cache)])
def update_engine(payload: SelectionRequest, db: Session = Depends(get_db),
                  actor: User = Depends(staff_only)):
    try:
        from .production_release import admin_selection, requested
        if requested() and payload.active_sales_engine == 'hermes' and (payload.expected_revision is None or not payload.expected_published_version_id):
            raise staff_config.EngineSelectionConflict('Refresh the published policy and confirm its revision.')
        with admin_selection():
            staff_config.select_sales_engine(db, engine=payload.active_sales_engine,
                note=payload.change_note, actor_id=actor.id,
                expected_revision=payload.expected_revision,
                expected_published_version_id=payload.expected_published_version_id)
        return staff_config.admin_engine_status(db)
    except staff_config.EngineSelectionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={'code': 'ENGINE_SELECTION_STALE',
            'message': str(exc)}) from exc
    except EngineUnavailable as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={'code': 'HERMES_NOT_READY',
            'message': str(exc)}) from exc
    except (EngineSelectionError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail='Invalid sales engine selection or policy.') from exc
