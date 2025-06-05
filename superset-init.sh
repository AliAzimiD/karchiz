#!/bin/bash
set -e

# Install additional Python packages if specified (e.g., database drivers)
if [ -n "${PIP_ADDITIONAL_REQUIREMENTS:-}" ]; then
  echo "Installing additional Python packages: ${PIP_ADDITIONAL_REQUIREMENTS}"
  pip install --no-cache-dir ${PIP_ADDITIONAL_REQUIREMENTS}
fi

# Initialize the database
superset db upgrade

# Create an admin user if it doesn't exist
superset fab create-admin \
    --username admin \
    --firstname admin \
    --lastname admin \
    --email admin@example.com \
    --password ${ADMIN_PASSWORD:-admin} || true

# Set up roles and permissions
superset init

# Configure default database connection in Superset
if [ -f "${APP_DB_PASSWORD_FILE:-/run/secrets/db_password}" ]; then
  export APP_DB_PASSWORD="$(cat ${APP_DB_PASSWORD_FILE:-/run/secrets/db_password})"
fi
echo "Setting up Superset database connection..."
python /app/scripts/create_superset_connection.py || true

# Start the Superset server
/usr/bin/run-server.sh
