#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 \
  --set app_password="$DEMO_APP_PASSWORD" <<'SQL'
CREATE ROLE managed_app LOGIN PASSWORD :'app_password';
CREATE DATABASE demo OWNER managed_app;
SQL
