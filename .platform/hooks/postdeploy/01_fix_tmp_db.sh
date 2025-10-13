#!/bin/bash
set -e

DB_PATH="/tmp/db.sqlite3"

# If DB doesn't exist, create it under webapp user
if [ ! -f "$DB_PATH" ]; then
    echo "Creating $DB_PATH..."
    sudo -u webapp touch "$DB_PATH"
fi

# Fix permissions and ownership
echo "Ensuring $DB_PATH is writable..."
chown webapp:webapp "$DB_PATH"
chmod 664 "$DB_PATH"
