"""Global-only Hermes policy and version store.

This is a P05 control plane, not an activation of the runtime in live traffic.
All values are server validated; tenant/project overrides never enter the API.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
import os
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session
from .config import HermesSettings, PROMPT_PATH
from .tool_schemas import SCHEMAS
from .staff_models import HermesGlobalSettings, HermesGlobalVersion
from . import engine_selection as routing

DEFAULT_MODEL = 'openai/gpt-4o-mini'
# Staff can *disable* a tool but never enable tools outside the pinned SDK
# contract, change per-tenant permissions, or bypass the gateway.
ALL_TOOLS = frozenset(SCHEMAS)
VISIBLE_TOOLS = sorted(ALL_TOOLS)
MODEL_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+:/-]{2,119}$')


class HermesGlobalPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    engine: str = 'hermes-agent'
    provider: str = 'openrouter'
    language: str = 'en'
    model: str = DEFAULT_MODEL
    allowed_models: list[str] = Field(default_factory=lambda: [DEFAULT_MODEL], min_length=1, max_length=30)
    system_prompt: str = Field(min_length=100, max_length=50000)
    max_iterations: int = Field(default=12, ge=1, le=12, strict=True)
    enabled_tools: list[str] = Field(default_factory=lambda: VISIBLE_TOOLS.copy())
    # Pausing prevents future activation. It does NOT unpause any Company/lead.
    enabled: bool = False

    @field_validator('engine')
    @classmethod
    def valid_engine(cls, value: str) -> str:
        if value != 'hermes-agent':
            raise ValueError('Hermes is the only supported sales conversation engine')
        return value

    @field_validator('provider')
    @classmethod
    def valid_provider(cls, value: str) -> str:
        if value != 'openrouter':
            raise ValueError('Only the approved OpenRouter provider is supported')
        return value

    @field_validator('language')
    @classmethod
    def valid_language(cls, value: str) -> str:
        if value != 'en':
            raise ValueError('Only English is supported in this release')
        return value

    @field_validator('allowed_models')
    @classmethod
    def valid_models(cls, models: list[str]) -> list[str]:
        if len(set(models)) != len(models) or any(not MODEL_NAME.fullmatch(model) for model in models):
            raise ValueError('Model identifiers must be unique, valid OpenRouter model slugs')
        return models

    @field_validator('enabled_tools')
    @classmethod
    def valid_tools(cls, tools: list[str]) -> list[str]:
        if len(set(tools)) != len(tools) or not set(tools).issubset(ALL_TOOLS):
            raise ValueError('Only the pinned Hermes business tools can be enabled')
        return tools

    @model_validator(mode='after')
    def match_model(self):
        if self.model not in self.allowed_models:
            raise ValueError('Selected model must be in the global allowlist')
        return self


def baseline() -> dict[str, Any]:
    return HermesGlobalPolicy(system_prompt=PROMPT_PATH.read_text(encoding='utf-8')).model_dump()


def normalized(value: dict[str, Any]) -> dict[str, Any]:
    return HermesGlobalPolicy.model_validate(value).model_dump()


def snapshot(db: Session) -> dict[str, Any]:
    settings = db.get(HermesGlobalSettings, 'global')
    return {
        'configuration': routing.prompt_policy(settings.configuration) if settings and settings.published_version_id else baseline(),
        'engine_selection': routing.routing_status(settings.configuration if settings else None),
        'published_version_id': settings.published_version_id if settings else None,
        'revision': settings.last_version if settings else 0,
        'configuration_scope': 'global',
        'runtime_connected_to_live': False,
        'available_tools': VISIBLE_TOOLS,
    }


def _locked_settings(db: Session) -> HermesGlobalSettings:
    row = db.query(HermesGlobalSettings).filter_by(id='global').with_for_update().one_or_none()
    if row is None:
        # Singleton row with fixed primary key. Caller transaction must roll back
        # if a concurrent first writer inserts first; retries are safe.
        row = HermesGlobalSettings(id='global', last_version=0, configuration=baseline())
        db.add(row)
        db.flush()
    return row


def versions(db: Session, *, offset: int = 0, limit: int = 20) -> dict:
    query = db.query(HermesGlobalVersion)
    return {'items': [serialize_version(r) for r in query.order_by(HermesGlobalVersion.version.desc()).offset(offset).limit(limit).all()],
            'total': query.count()}


def serialize_version(value: HermesGlobalVersion, *, include_config: bool = False) -> dict:
    result = {'id': value.id, 'version': value.version, 'is_published': value.is_published,
              'created_at': value.created_at, 'published_at': value.published_at,
              'change_note': value.change_note, 'created_by_user_id': value.created_by_user_id}
    if include_config:
        result['configuration'] = routing.prompt_policy(value.configuration)
        if routing.SELECTION_KEY in value.configuration:
            result['active_sales_engine_at_change'] = value.configuration[routing.SELECTION_KEY]
    return result


def find_version(db: Session, version_id: str) -> HermesGlobalVersion:
    item = db.query(HermesGlobalVersion).filter_by(id=version_id).one_or_none()
    if item is None:
        raise LookupError('Unknown Hermes configuration version')
    return item


def create_draft(db: Session, *, configuration: dict, note: str, actor_id: str) -> dict:
    policy = normalized(configuration)
    row = _locked_settings(db)
    row.last_version += 1
    version = HermesGlobalVersion(version=row.last_version, configuration=policy,
                                  change_note=note[:500], created_by_user_id=actor_id, is_published=False)
    db.add(version)
    db.commit()
    db.refresh(version)
    return serialize_version(version)


def publish(db: Session, *, version_id: str, actor_id: str) -> dict:
    row = _locked_settings(db)
    version = find_version(db, version_id)
    # Validate even previously stored data; never allow a malformed draft.
    policy = normalized(routing.prompt_policy(version.configuration))
    selected_engine = routing.read_engine(row.configuration)
    stored_selection = ({routing.SELECTION_KEY: selected_engine}
                        if routing.SELECTION_KEY in row.configuration else {})
    db.query(HermesGlobalVersion).filter(HermesGlobalVersion.is_published.is_(True)).update(
        {HermesGlobalVersion.is_published: False}, synchronize_session=False)
    version.is_published = True
    version.published_at = datetime.now(timezone.utc)
    row.published_version_id = version.id
    row.configuration = {**policy, **stored_selection}
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return snapshot(db)


def restore(db: Session, *, version_id: str, actor_id: str) -> dict:
    row = _locked_settings(db)
    source = find_version(db, version_id)
    policy = normalized(routing.prompt_policy(source.configuration))
    selected_engine = routing.read_engine(row.configuration)
    stored_selection = ({routing.SELECTION_KEY: selected_engine}
                        if routing.SELECTION_KEY in row.configuration else {})
    row.last_version += 1
    db.query(HermesGlobalVersion).filter(HermesGlobalVersion.is_published.is_(True)).update(
        {HermesGlobalVersion.is_published: False}, synchronize_session=False)
    new = HermesGlobalVersion(version=row.last_version, configuration=policy,
                              change_note=f'Restored from global version {source.version}',
                              created_by_user_id=actor_id, published_at=datetime.now(timezone.utc), is_published=True)
    db.add(new)
    db.flush()
    row.published_version_id = new.id
    row.configuration = {**policy, **stored_selection}
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return snapshot(db)


def settings_for_turn(db: Session) -> tuple[HermesSettings, str | None, frozenset[str]]:
    """Pin one published version for a future isolated worker turn.

    Do not call from the legacy worker. Tool allowlisting in the SDK is still
    mandatory at P07; this method deliberately does not activate any channel.
    """
    current = snapshot(db)
    policy = HermesGlobalPolicy.model_validate(current['configuration'])
    if not policy.enabled:
        raise PermissionError('Global Hermes runtime is not enabled for live sales')
    settings = HermesSettings(api_key=os.environ.get('OPENROUTER_API_KEY', ''),
                              model=policy.model, max_iterations=policy.max_iterations,
                              prompt=policy.system_prompt)
    return settings, current['published_version_id'], frozenset(policy.enabled_tools)


def engine_status(db: Session) -> dict[str, Any]:
    """Read the actual selector, without loading credentials or the SDK."""
    row = db.get(HermesGlobalSettings, 'global')
    return {**routing.routing_status(row.configuration if row else None),
            'published_version_id': row.published_version_id if row else None,
            'revision': row.last_version if row else 0}


def select_sales_engine(db: Session, *, engine: str, note: str, actor_id: str) -> dict[str, Any]:
    """Explicit audited change; prompt publish/restore cannot change the engine.

    Uses existing P05 tables only. In HEI-01A Hermes activation is denied, even
    when an older Hermes prompt version was published with enabled=True.
    """
    routing.require_selectable(engine)
    if not isinstance(note, str) or not note.strip() or len(note) > 400:
        raise ValueError('A change note of 1–400 characters is required.')
    row = _locked_settings(db)
    try:
        previous = routing.read_engine(row.configuration)
    except routing.EngineSelectionError:
        previous = None
    if previous == engine:
        # No-op, not a synthetic version or a hidden prompt publication.
        db.rollback()
        return engine_status(db)
    policy = normalized(routing.prompt_policy(row.configuration))
    if engine == routing.HERMES and (not row.published_version_id or not policy['enabled']):
        raise routing.EngineUnavailable('Publish an enabled Hermes policy before selecting Hermes.')
    row.last_version += 1
    now = datetime.now(timezone.utc)
    db.query(HermesGlobalVersion).filter(HermesGlobalVersion.is_published.is_(True)).update(
        {HermesGlobalVersion.is_published: False}, synchronize_session=False)
    config = {**policy, routing.SELECTION_KEY: engine}
    change = HermesGlobalVersion(version=row.last_version, configuration=deepcopy(config),
        change_note=f'Sales engine {previous or "invalid"} -> {engine}: {note.strip()}',
        created_by_user_id=actor_id, published_at=now, is_published=True)
    db.add(change)
    db.flush()
    row.published_version_id = change.id
    row.configuration = config
    row.updated_at = now
    db.commit()
    return engine_status(db)
