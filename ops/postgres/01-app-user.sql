-- Executed by the official entrypoint only for a new, empty volume.
-- Read passwords via the environment rather than process command arguments.
\getenv app_user APP_DB_USER
\getenv app_password APP_DB_PASSWORD
\getenv db_name POSTGRES_DB
CREATE ROLE :"app_user" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
ALTER DATABASE :"db_name" OWNER TO :"app_user";
