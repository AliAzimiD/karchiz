# Use Python 3.11-slim as a lightweight base image
FROM python:3.11-slim

# ARG to suppress tzdata interactive prompts (optional for Debian/Ubuntu-based images)
ARG DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# Set environment variables for consistent behavior
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SCRAPER_ENV=production \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    TZ=UTC

# Install minimal system dependencies:
#  - build-essential & libpq-dev required for psycopg2 compilation
#  - cron, tzdata, logrotate needed for scheduled tasks, logs
#  - gosu for dropping privileges
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    postgresql-client \
    libpq-dev \
    cron \
    tzdata \
    logrotate \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for running the application (security best practice)
RUN groupadd -r scraper && useradd -r -g scraper scraper -u 1000

# Create directory structure with proper permissions
RUN mkdir -p /app/job_data/raw_data \
    /app/job_data/processed_data \
    /app/job_data/logs \
    /app/config \
    /app/health \
    && touch /app/job_data/logs/cron.log \
    && chown -R scraper:scraper /app \
    && chmod -R 755 /app/job_data

# Copy requirements first for Docker layer caching
COPY --chown=scraper:scraper requirements.txt .

# Install Python dependencies
# NOTE: We install flask & psutil for the health check service; remove 'requests'
# if not strictly needed in the main application (health check uses 'curl').
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir flask psutil

# Configure log rotation for logs inside /app/job_data/logs
RUN echo "/app/job_data/logs/*.log {\n\
  rotate 7\n\
  daily\n\
  missingok\n\
  notifempty\n\
  compress\n\
  delaycompress\n\
  create 0644 scraper scraper\n\
}" > /etc/logrotate.d/scraper \
    && chmod 0644 /etc/logrotate.d/scraper

# Set up cron jobs for scheduled scraping every 6 hours + daily logrotate
RUN echo "0 */6 * * * cd /app && /usr/local/bin/python /app/main.py >> /app/job_data/logs/cron.log 2>&1" \
    > /etc/cron.d/scraper-cron \
    && echo "0 0 * * * /usr/sbin/logrotate /etc/logrotate.d/scraper --state /app/job_data/logs/logrotate.status" \
    >> /etc/cron.d/scraper-cron \
    && chmod 0644 /etc/cron.d/scraper-cron

# Create the health check API
# Note how we keep the entire Python script in single quotes,
# so we can use normal double quotes for @app.route("/health").
RUN echo 'from flask import Flask, jsonify\n\
import psutil\n\
import os\n\
import time\n\
\n\
app = Flask(__name__)\n\
start_time = time.time()\n\
\n\
@app.route("/health")\n\
def health():\n\
    uptime = time.time() - start_time\n\
    log_dir = "/app/job_data/logs"\n\
    log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]\n\
    latest_log = None\n\
    if log_files:\n\
        latest_log = max([os.path.join(log_dir, f) for f in log_files], key=os.path.getmtime)\n\
\n\
    return jsonify({\n\
        "status": "healthy",\n\
        "uptime_seconds": uptime,\n\
        "memory_usage_percent": psutil.virtual_memory().percent,\n\
        "cpu_usage_percent": psutil.cpu_percent(interval=1),\n\
        "disk_usage_percent": psutil.disk_usage("/").percent,\n\
        "latest_log": latest_log,\n\
        "environment": os.environ.get("SCRAPER_ENV", "unknown")\n\
    })\n\
\n\
if __name__ == "__main__":\n\
    app.run(host="0.0.0.0", port=8081)\n' > /app/health/app.py

# Copy the entire application (including entrypoint.sh)
COPY --chown=scraper:scraper . .

# Ensure entrypoint.sh has correct permissions and line endings
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod 755 /app/entrypoint.sh

# Docker HEALTHCHECK - calls the flask health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -sf http://localhost:8081/health || exit 1

# Expose the health check port
EXPOSE 8081

# Use a volume for /app/job_data to persist data and logs
VOLUME ["/app/job_data"]

# Switch to non-root user for runtime (Optional if you want to remain root for cron).
# Currently, we keep "USER root" because cron sometimes requires root-level permissions
# to write /var/run/crond.pid. If that's resolved, we could switch to 'USER scraper'.
USER root

# Set the entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
