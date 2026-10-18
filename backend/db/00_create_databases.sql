-- backend/db/00_create_databases.sql
-- Run as postgres superuser to bootstrap local development and testing databases.
-- Usage: psql -U postgres -f backend/db/00_create_databases.sql
-- Note: Roles (gympro_app, gympro_seed, gympro_analytics) and grants come from schema.sql (Spec 6.14).

SELECT 'CREATE DATABASE gympro'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gympro')\gexec

SELECT 'CREATE DATABASE gympro_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gympro_test')\gexec
