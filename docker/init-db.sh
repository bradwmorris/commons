#!/usr/bin/env bash
# Official postgres image invokes this only for an EMPTY volume. Never an upgrade step.
set -euo pipefail
export COMMONS_MIGRATOR_PASSWORD="$(cat /run/secrets/migrator_password)"
export COMMONS_APP_PASSWORD="$(cat /run/secrets/app_password)"
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv migrator_password COMMONS_MIGRATOR_PASSWORD
\getenv app_password COMMONS_APP_PASSWORD
CREATE ROLE commons_migrator LOGIN PASSWORD :'migrator_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE commons_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER DATABASE commons OWNER TO commons_migrator;
REVOKE ALL ON DATABASE commons FROM PUBLIC;
GRANT CONNECT ON DATABASE commons TO commons_app;
ALTER SCHEMA public OWNER TO commons_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO commons_app;
CREATE EXTENSION vector;
SET ROLE commons_migrator;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO commons_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO commons_app;
SQL
unset COMMONS_MIGRATOR_PASSWORD COMMONS_APP_PASSWORD
