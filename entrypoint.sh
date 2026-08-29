#!/usr/bin/env bash

set -e

python manage.py collectstatic --noinput
python manage.py migrate --noinput

echo "Creating initial admin if necessary..."
python manage.py create_initial_admin

python -m gunicorn --bind 0.0.0.0:8000 --workers 3 zeiterfassung.wsgi:application
