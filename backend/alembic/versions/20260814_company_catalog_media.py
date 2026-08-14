"""Add company media and structured project property types.

Revision ID: 20260814_company_catalog_media
Revises: 20260814_project_onboarding_ux
"""

from alembic import op
import sqlalchemy as sa


revision = "20260814_company_catalog_media"
down_revision = "20260814_project_onboarding_ux"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscription_plans",
        sa.Column("max_property_types_per_project", sa.Integer(), nullable=False, server_default="20"),
    )
    op.create_table(
        "company_media_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="logo_candidate"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=150), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["company_onboarding_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "sha256", name="uq_company_media_company_sha256"),
    )
    op.create_index("ix_company_media_assets_company_id", "company_media_assets", ["company_id"])
    op.create_index("ix_company_media_assets_role", "company_media_assets", ["role"])

    op.create_table(
        "project_property_types",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Float(), nullable=True),
        sa.Column("area_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("area_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("area_unit", sa.String(length=20), nullable=True),
        sa.Column("total_units", sa.Integer(), nullable=True),
        sa.Column("available_units", sa.Integer(), nullable=True),
        sa.Column("starting_price", sa.Numeric(16, 2), nullable=True),
        sa.Column("maximum_price", sa.Numeric(16, 2), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("inventory_updated_at", sa.DateTime(), nullable=True),
        sa.Column("images_status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="confirmed"),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_property_types_project_name"),
    )
    op.create_index("ix_project_property_types_project_id", "project_property_types", ["project_id"])

    op.create_table(
        "project_property_type_media",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("property_type_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("caption", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["property_type_id"], ["project_property_types.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["project_onboarding_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("property_type_id", "source_id", name="uq_property_type_media_source"),
    )
    op.create_index("ix_project_property_type_media_property_type_id", "project_property_type_media", ["property_type_id"])
    op.create_index("ix_project_property_type_media_source_id", "project_property_type_media", ["source_id"])

    op.create_table(
        "sales_asset_shares",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["project_onboarding_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("token_hash"),
    )
    for name, column in (
        ("ix_sales_asset_shares_company_id", "company_id"),
        ("ix_sales_asset_shares_project_id", "project_id"),
        ("ix_sales_asset_shares_lead_id", "lead_id"),
        ("ix_sales_asset_shares_source_id", "source_id"),
        ("ix_sales_asset_shares_token_hash", "token_hash"),
        ("ix_sales_asset_shares_expires_at", "expires_at"),
    ):
        op.create_index(name, "sales_asset_shares", [column])

    # Existing unit inventory becomes a confirmed structured catalog without
    # inventing aggregate rows for legacy free-text typologies.
    op.execute(sa.text("""
        INSERT INTO project_property_types (
            id, project_id, name, bedrooms, bathrooms, area_min, area_max, area_unit,
            total_units, available_units, starting_price, maximum_price, currency,
            features, inventory_updated_at, images_status, review_status,
            source_reference, sort_order, created_at, updated_at
        )
        SELECT
            md5(pu.project_id || ':' || COALESCE(pu.typology, 'Unclassified')),
            pu.project_id,
            COALESCE(pu.typology, 'Unclassified'),
            MIN(pu.bedrooms), MIN(pu.bathrooms), MIN(pu.area), MAX(pu.area), 'm2',
            COUNT(*),
            SUM(CASE WHEN pu.status = 'available' THEN 1 ELSE 0 END),
            MIN(pu.list_price), MAX(pu.list_price), COALESCE(MAX(pu.currency), 'USD'),
            '[]'::json, COALESCE(MAX(pu.inventory_updated_at), CURRENT_TIMESTAMP),
            'pending', 'confirmed', 'Migrated from unit inventory', 0,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM project_units pu
        WHERE pu.list_price IS NOT NULL
        GROUP BY pu.project_id, COALESCE(pu.typology, 'Unclassified')
        ON CONFLICT (project_id, name) DO NOTHING
    """))
    op.execute(sa.text("""
        UPDATE project_profiles pp
        SET profile_data = jsonb_set(
                COALESCE(pp.profile_data::jsonb, '{}'::jsonb),
                '{project_cover}',
                to_jsonb((
                    SELECT pos.id::text
                    FROM project_onboarding_sources pos
                    WHERE pos.project_id = pp.project_id
                      AND pos.kind = 'IMAGE'
                      AND pos.status = 'READY'
                      AND pos.storage_path IS NOT NULL
                    ORDER BY pos.is_primary DESC, pos.created_at ASC
                    LIMIT 1
                )),
                true
            )::json,
            field_states = jsonb_set(
                COALESCE(pp.field_states::jsonb, '{}'::jsonb),
                '{project_cover}',
                jsonb_build_object('status', 'confirmed', 'applicable', TRUE),
                true
            )::json
        WHERE EXISTS (
            SELECT 1 FROM project_onboarding_sources pos
            WHERE pos.project_id = pp.project_id
              AND pos.kind = 'IMAGE'
              AND pos.status = 'READY'
              AND pos.storage_path IS NOT NULL
        )
    """))
    op.execute(sa.text("""
        UPDATE project_profiles pp
        SET profile_data = jsonb_set(
                COALESCE(pp.profile_data::jsonb, '{}'::jsonb),
                '{property_type_catalog}',
                COALESCE((
                    SELECT jsonb_agg(ppt.id)
                    FROM project_property_types ppt
                    WHERE ppt.project_id = pp.project_id AND ppt.review_status = 'confirmed'
                ), '[]'::jsonb),
                true
            )::json,
            field_states = jsonb_set(
                COALESCE(pp.field_states::jsonb, '{}'::jsonb),
                '{property_type_catalog}',
                jsonb_build_object('status', 'confirmed', 'applicable', TRUE),
                true
            )::json
        WHERE EXISTS (
            SELECT 1 FROM project_property_types ppt
            WHERE ppt.project_id = pp.project_id AND ppt.review_status = 'confirmed'
        )
    """))
    op.execute(
        sa.text("INSERT INTO schema_versions (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP) ON CONFLICT (version) DO NOTHING")
        .bindparams(version=revision)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schema_versions WHERE version = :version").bindparams(version=revision))
    for name in (
        "ix_sales_asset_shares_expires_at", "ix_sales_asset_shares_token_hash",
        "ix_sales_asset_shares_source_id", "ix_sales_asset_shares_lead_id",
        "ix_sales_asset_shares_project_id", "ix_sales_asset_shares_company_id",
    ):
        op.drop_index(name, table_name="sales_asset_shares")
    op.drop_table("sales_asset_shares")
    op.drop_index("ix_project_property_type_media_source_id", table_name="project_property_type_media")
    op.drop_index("ix_project_property_type_media_property_type_id", table_name="project_property_type_media")
    op.drop_table("project_property_type_media")
    op.drop_index("ix_project_property_types_project_id", table_name="project_property_types")
    op.drop_table("project_property_types")
    op.drop_index("ix_company_media_assets_role", table_name="company_media_assets")
    op.drop_index("ix_company_media_assets_company_id", table_name="company_media_assets")
    op.drop_table("company_media_assets")
    op.drop_column("subscription_plans", "max_property_types_per_project")
