from fastapi import APIRouter, HTTPException, status
from sqlalchemy import inspect, text

from app.db.postgres import engine
from app.db.schema import CURRENT_SCHEMA_VERSION


router = APIRouter()

REQUIRED_COLUMNS = {
    "onboarding_messages": {"ui_payload", "response_payload", "in_reply_to_message_id"},
    "project_messages": {"ui_payload", "response_payload", "in_reply_to_message_id"},
    "onboarding_source_jobs": {
        "id", "scope", "company_id", "project_id", "source_id", "message_id",
        "status", "attempts", "idempotency_key", "available_at",
    },
}


@router.get("/ready")
def readiness() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            inspector = inspect(connection)
            missing_tables = [name for name in REQUIRED_COLUMNS if not inspector.has_table(name)]
            missing_columns = {
                table: sorted(required - {column["name"] for column in inspector.get_columns(table)})
                for table, required in REQUIRED_COLUMNS.items()
                if table not in missing_tables
            }
            missing_columns = {table: columns for table, columns in missing_columns.items() if columns}
            version_ok = False
            if inspector.has_table("schema_versions"):
                version_ok = connection.execute(
                    text("SELECT 1 FROM schema_versions WHERE version = :version"),
                    {"version": CURRENT_SCHEMA_VERSION},
                ).first() is not None
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "reason": "database_unavailable"},
        ) from exc

    if missing_tables or missing_columns or not version_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "not_ready",
                "reason": "schema_incompatible",
                "missing_tables": missing_tables,
                "missing_columns": missing_columns,
                "required_schema_version": CURRENT_SCHEMA_VERSION,
            },
        )
    return {"status": "ready", "schema_version": CURRENT_SCHEMA_VERSION}
