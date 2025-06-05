#!/bin/bash
set -e

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

# Start the Superset server
/usr/bin/run-server.sh
