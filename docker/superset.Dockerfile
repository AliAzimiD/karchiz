FROM apache/superset:latest
RUN pip install --no-cache-dir psycopg2-binary
COPY superset-init.sh /app/superset-init.sh
