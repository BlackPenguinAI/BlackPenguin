BEGIN;

-- Support both the SQLAlchemy enum (uppercase labels) and the legacy DDL enum
-- (lowercase labels) without guessing the production type name.
DO $$
DECLARE
    role_type TEXT;
    assistant_label TEXT;
BEGIN
    SELECT t.typname
      INTO role_type
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_type t ON t.oid = a.atttypid
     WHERE c.relname = 'users'
       AND a.attname = 'role'
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND t.typtype = 'e'
     LIMIT 1;

    IF role_type IS NOT NULL THEN
        assistant_label := CASE
            WHEN EXISTS (
                SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
                 WHERE t.typname = role_type AND e.enumlabel = 'ADMIN'
            ) THEN 'ASSISTANT'
            ELSE 'assistant'
        END;
        EXECUTE format(
            'ALTER TYPE %I ADD VALUE IF NOT EXISTS %L',
            role_type,
            assistant_label
        );
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'subscription_plans' AND column_name = 'max_admins'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'subscription_plans' AND column_name = 'max_assistants'
    ) THEN
        ALTER TABLE subscription_plans RENAME COLUMN max_admins TO max_assistants;
    ELSIF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'subscription_plans' AND column_name = 'max_assistants'
    ) THEN
        ALTER TABLE subscription_plans ADD COLUMN max_assistants INTEGER NOT NULL DEFAULT 0;
    END IF;
END $$;

ALTER TABLE subscription_plans ALTER COLUMN max_assistants SET DEFAULT 0;
UPDATE subscription_plans SET max_assistants = 0 WHERE max_assistants IS NULL;
ALTER TABLE subscription_plans ALTER COLUMN max_assistants SET NOT NULL;

-- Stop instead of silently choosing an administrator when legacy duplicates exist.
DO $$
DECLARE
    role_type TEXT;
    admin_label TEXT;
    duplicate_company TEXT;
BEGIN
    SELECT t.typname
      INTO role_type
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_type t ON t.oid = a.atttypid
     WHERE c.relname = 'users'
       AND a.attname = 'role'
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND t.typtype = 'e'
     LIMIT 1;

    IF role_type IS NULL THEN
        RAISE EXCEPTION 'users.role must be a PostgreSQL enum before applying this migration';
    END IF;

    admin_label := CASE
        WHEN EXISTS (
            SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
             WHERE t.typname = role_type AND e.enumlabel = 'ADMIN'
        ) THEN 'ADMIN'
        ELSE 'admin'
    END;

    EXECUTE format(
        'SELECT company_id FROM users WHERE company_id IS NOT NULL AND role = %L::%I '
        'GROUP BY company_id HAVING COUNT(*) > 1 LIMIT 1',
        admin_label,
        role_type
    ) INTO duplicate_company;

    IF duplicate_company IS NOT NULL THEN
        RAISE EXCEPTION 'Company % has more than one administrator; resolve duplicates before retrying', duplicate_company;
    END IF;

    EXECUTE format(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_users_one_admin_per_company '
        'ON users (company_id) WHERE company_id IS NOT NULL AND role = %L::%I',
        admin_label,
        role_type
    );
END $$;

-- Operational user identities are not Company Profile fields.
UPDATE company_profiles
   SET profile_data = (COALESCE(profile_data, '{}'::json)::jsonb - 'primary_black_penguin_administrator')::json,
       field_states = (COALESCE(field_states, '{}'::json)::jsonb - 'primary_black_penguin_administrator')::json,
       field_sources = (COALESCE(field_sources, '{}'::json)::jsonb - 'primary_black_penguin_administrator')::json
 WHERE COALESCE(profile_data, '{}'::json)::jsonb ? 'primary_black_penguin_administrator'
    OR COALESCE(field_states, '{}'::json)::jsonb ? 'primary_black_penguin_administrator'
    OR COALESCE(field_sources, '{}'::json)::jsonb ? 'primary_black_penguin_administrator';

COMMIT;
