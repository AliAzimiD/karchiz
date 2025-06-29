FROM apache/superset:latest

USER root
RUN pip install --no-cache-dir psycopg2-binary \
    && su -s /bin/sh superset -c "pip install --user --no-cache-dir psycopg2-binary"
USER superset

COPY superset-init.sh /app/superset-init.sh
COPY superset-init.sh /app/superset-init.sh
