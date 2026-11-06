-- One-off, SAFE initialisation of the IAM database roles and schema. Run by a DBA / superuser:
--   psql -d bank-cms -v migrator_pw="'...'" -v runtime_pw="'...'" -f scripts/db/init_iam_roles.sql
-- Passwords are supplied as psql variables so they never live in this file.
-- Touches only the `iam` schema; no other service's schema receives any privilege.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'iam_migrator') THEN
    CREATE ROLE iam_migrator LOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'iam_user') THEN
    CREATE ROLE iam_user LOGIN;
  END IF;
END $$;

ALTER ROLE iam_migrator PASSWORD :migrator_pw;
ALTER ROLE iam_user PASSWORD :runtime_pw;

-- Migration role owns the schema (DDL); runtime role only reads/writes rows.
CREATE SCHEMA IF NOT EXISTS iam AUTHORIZATION iam_migrator;
GRANT CONNECT ON DATABASE "bank-cms" TO iam_migrator, iam_user;
GRANT USAGE ON SCHEMA iam TO iam_user;
ALTER ROLE iam_migrator SET search_path = iam;
ALTER ROLE iam_user SET search_path = iam;

-- Objects created later by iam_migrator are automatically usable by iam_user.
ALTER DEFAULT PRIVILEGES FOR ROLE iam_migrator IN SCHEMA iam
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO iam_user;
ALTER DEFAULT PRIVILEGES FOR ROLE iam_migrator IN SCHEMA iam
  GRANT USAGE, SELECT ON SEQUENCES TO iam_user;
-- NOTE: migration 0001 narrows audit_logs for iam_user to SELECT, INSERT (append-only).

REVOKE ALL ON SCHEMA iam FROM PUBLIC;
