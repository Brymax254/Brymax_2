#!/bin/bash
# Development entrypoint script
set -e

# Wait for database if needed
# while ! nc -z $DB_HOST $DB_PORT; do
#   echo "Waiting for PostgreSQL..."
#   sleep 1
# done

python manage.py migrate
python manage.py runserver 0.0.0.0:8000
