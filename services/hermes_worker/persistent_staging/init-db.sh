#!/bin/sh
(
set -eu
# Executed only by postgres image when its new named volume is initialized.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v instance="$HEI06A2_INSTANCE" <<'SQL'
CREATE TABLE hei06a2_guard (purpose text PRIMARY KEY, instance_id text NOT NULL, candidate_commit text);
INSERT INTO hei06a2_guard VALUES ('hei06a2-closed-persistent-v1', :'instance', NULL);
SQL
)
