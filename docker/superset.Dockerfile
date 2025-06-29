FROM apache/superset:latest

# Install the PostgreSQL driver inside Superset's virtual environment
USER root
RUN /app/.venv/bin/pip install --no-cache-dir psycopg2-binary
USER superset

COPY superset-init.sh /app/superset-init.sh
