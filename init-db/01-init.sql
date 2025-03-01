-- Create schema and extensions
CREATE SCHEMA IF NOT EXISTS public;

-- Create a health check function
CREATE OR REPLACE FUNCTION public.health_check()
RETURNS TEXT AS $$
BEGIN
    RETURN 'OK';
END;
$$ LANGUAGE plpgsql;

-- Set default permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jobuser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO jobuser;
