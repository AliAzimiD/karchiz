# Use Python 3.11 slim as base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SCRAPER_ENV=production \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    TZ=UTC

# Install system dependencies
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

# Create non-root user for application
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

# Copy requirements first to leverage Docker cache
COPY --chown=scraper:scraper requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir flask requests psutil

# Set up log rotation
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

# Set up cron job for scheduled scraping (runs every 6 hours)
RUN echo "0 */6 * * * cd /app && /usr/local/bin/python /app/main.py >> /app/job_data/logs/cron.log 2>&1" > /etc/cron.d/scraper-cron \
    && echo "0 0 * * * /usr/sbin/logrotate /etc/logrotate.d/scraper --state /app/job_data/logs/logrotate.status" >> /etc/cron.d/scraper-cron \
    && chmod 0644 /etc/cron.d/scraper-cron

# Create a simple health check API
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
    app.run(host="0.0.0.0", port=8081)\n\
' > /app/health/app.py

# Create a comprehensive entrypoint script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Function to handle signals\n\
cleanup() {\n\
    echo "Received signal to shut down..."\n\
    if [ -n "$HEALTH_PID" ]; then\n\
        echo "Stopping health check service..."\n\
        kill -TERM "$HEALTH_PID" 2>/dev/null || true\n\
    fi\n\
    if [ "$ENABLE_CRON" = "true" ]; then\n\
        echo "Stopping cron service..."\n\
        service cron stop || true\n\
    fi\n\
    echo "Cleanup complete, exiting..."\n\
    exit 0\n\
}\n\
\n\
# Register signal handlers\n\
trap cleanup SIGTERM SIGINT\n\
\n\
# Validate required environment variables\n\
if [ -z "$SCRAPER_ENV" ]; then\n\
    echo "ERROR: SCRAPER_ENV environment variable is not set!"\n\
    exit 1\n\
fi\n\
\n\
echo "Starting job scraper in $SCRAPER_ENV environment..."\n\
\n\
# Debug information\n\
echo "Current directory structure and permissions:"\n\
ls -la /app/job_data/logs\n\
\n\
# Fix permissions for mounted volumes\n\
echo "Ensuring proper permissions for all directories..."\n\
chown -R scraper:scraper /app/job_data\n\
chmod -R 755 /app/job_data\n\
\n\
# Clean up existing log files - handle ownership issues\n\
echo "Cleaning up old log files ownership..."\n\
find /app/job_data/logs -type f -name "*.log" -exec chown scraper:scraper {} \\;\n\
find /app/job_data/logs -type f -name "*.log" -exec chmod 644 {} \\;\n\
\n\
# Ensure log directory has proper permissions\n\
touch /app/job_data/logs/cron.log\n\
chown scraper:scraper /app/job_data/logs/cron.log\n\
chmod 644 /app/job_data/logs/cron.log\n\
\n\
# Start health check service\n\
echo "Starting health check service on port 8081..."\n\
python /app/health/app.py &\n\
HEALTH_PID=$!\n\
echo "Health check service started with PID $HEALTH_PID"\n\
\n\
# Wait for health service to start\n\
echo "Waiting for health service to be available..."\n\
for i in {1..10}; do\n\
    if curl -s http://localhost:8081/health > /dev/null; then\n\
        echo "Health service is up and running!"\n\
        break\n\
    fi\n\
    if [ "$i" -eq 10 ]; then\n\
        echo "ERROR: Health service failed to start!"\n\
        exit 1\n\
    fi\n\
    echo "Waiting for health service... ($i/10)"\n\
    sleep 1\n\
done\n\
\n\
if [ "$ENABLE_CRON" = "true" ]; then\n\
    echo "Starting cron service..."\n\
    service cron start || { echo "Failed to start cron service"; exit 1; }\n\
    echo "Cron service started successfully"\n\
    \n\
    # Verify cron is running\n\
    if ! service cron status > /dev/null; then\n\
        echo "ERROR: Cron service is not running!"\n\
        exit 1\n\
    fi\n\
    echo "Cron service verified running"\n\
fi\n\
\n\
if [ "$RUN_ON_START" = "true" ]; then\n\
    echo "Running initial scraper job..."\n\
    # Create a timestamp for the log file\n\
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")\n\
    LOG_FILE="/app/job_data/logs/scraper_${TIMESTAMP}.log"\n\
    touch "$LOG_FILE"\n\
    chown scraper:scraper "$LOG_FILE"\n\
    \n\
    echo "Logging to $LOG_FILE"\n\
    \n\
    # Run the scraper as the scraper user\n\
    gosu scraper bash -c "cd /app && python /app/main.py > $LOG_FILE 2>&1" || {\n\
        echo "Initial scraper job failed with exit code $?. Checking permissions:"\n\
        ls -la /app/job_data/logs\n\
        echo "Last 20 lines of logs:"\n\
        tail -n 20 "$LOG_FILE" 2>/dev/null || echo "No log file found at $LOG_FILE"\n\
        exit 1;\n\
    }\n\
    \n\
    echo "Initial scraper job completed successfully"\n\
fi\n\
\n\
if [ "$ENABLE_CRON" = "true" ]; then\n\
    echo "Keeping container running for cron jobs..."\n\
    # Keep container running but still respond to signals\n\
    while true; do\n\
        tail -f /app/job_data/logs/cron.log & wait $!\n\
    done\n\
else\n\
    echo "Running scraper once..."\n\
    # Create a timestamp for the log file\n\
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")\n\
    LOG_FILE="/app/job_data/logs/scraper_${TIMESTAMP}.log"\n\
    touch "$LOG_FILE"\n\
    chown scraper:scraper "$LOG_FILE"\n\
    \n\
    echo "Logging to $LOG_FILE"\n\
    \n\
    # Run the scraper as the scraper user\n\
    gosu scraper bash -c "cd /app && python /app/main.py > $LOG_FILE 2>&1" || {\n\
        echo "Scraper job failed with exit code $?. Checking permissions:"\n\
        ls -la /app/job_data/logs\n\
        echo "Last 20 lines of logs:"\n\
        tail -n 20 "$LOG_FILE" 2>/dev/null || echo "No log file found at $LOG_FILE"\n\
        exit 1;\n\
    }\n\
    \n\
    echo "Scraper job completed successfully"\n\
fi' > /app/entrypoint.sh \
    && chmod +x /app/entrypoint.sh

# Copy the rest of the application
COPY --chown=scraper:scraper . .

# Configure healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -sf http://localhost:8081/health || exit 1

# Expose health check port
EXPOSE 8081

# Set volumes for persistent data
VOLUME ["/app/job_data"]

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
