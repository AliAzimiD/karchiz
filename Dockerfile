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
    && touch /app/job_data/logs/cron.log \
    && chown -R scraper:scraper /app \
    && chmod -R 755 /app/job_data

# Copy requirements first for Docker layer caching
COPY --chown=scraper:scraper requirements.txt .

# Install Python dependencies
# Install requirements and psutil used by the health check metrics
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir psutil

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
RUN echo "0 */6 * * * cd /app && ENABLE_HEALTH_CHECK=false /usr/local/bin/python /app/main.py >> /app/job_data/logs/cron.log 2>&1" \
    > /etc/cron.d/scraper-cron \
    && echo "0 0 * * * /usr/sbin/logrotate /etc/logrotate.d/scraper --state /app/job_data/logs/logrotate.status" \
    >> /etc/cron.d/scraper-cron \
    && chmod 0644 /etc/cron.d/scraper-cron


# Copy the entire application (including entrypoint.sh)
COPY --chown=scraper:scraper . .

# Ensure entrypoint.sh has correct permissions and line endings
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod 755 /app/entrypoint.sh

# Docker HEALTHCHECK - calls the aiohttp health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -sf http://localhost:8080/health || exit 1

# Expose the health check port
EXPOSE 8080

# Use a volume for /app/job_data to persist data and logs
VOLUME ["/app/job_data"]

# Switch to non-root user for runtime (Optional if you want to remain root for cron).
# Currently, we keep "USER root" because cron sometimes requires root-level permissions
# to write /var/run/crond.pid. If that's resolved, we could switch to 'USER scraper'.
USER root

# Set the entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
