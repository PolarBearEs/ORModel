#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

echo "ORModel Entrypoint: Starting..."

# Optional: Add a loop here to wait for the database to be ready, especially for external DBs.
# Example for PostgreSQL:
# echo "Waiting for PostgreSQL..."
# while ! pg_isready -h $DB_HOST -p $DB_PORT -U $DB_USER -q -t 5; do
#   echo "PostgreSQL is unavailable - sleeping"
#   sleep 1
# done
# echo "PostgreSQL is up - continuing..."
# Requires DB_HOST, DB_PORT, DB_USER env vars and pg_isready (install postgresql-client in Dockerfile if needed)

# Navigate to the directory containing alembic.ini to run migrations
# Ensure this path matches your project structure inside the container
if [ -d "/app/examples" ] && [ -f "/app/examples/alembic.ini" ]; then
  echo "Running database migrations..."
  cd /app/examples
  # Run Alembic using the alembic executable installed via uv/pip
  # The ALEMBIC_DATABASE_URL environment variable should be set correctly
  alembic upgrade head
  cd /app # Navigate back to the main WORKDIR
  echo "Database migrations finished."
else
  echo "Warning: Alembic directory or alembic.ini not found in /app/examples. Skipping migrations."
fi


# Execute the command passed as arguments to this script (the CMD from Dockerfile)
echo "Starting application via: $@"
exec "$@"