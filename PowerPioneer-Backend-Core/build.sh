#!/bin/bash

# Exit if any command fails
set -e

echo "Python Version:"
python3 --version

echo "Django Check:"
python3 manage.py check

echo "Collecting static files..."
python3 manage.py collectstatic --noinput

echo "Static Collection completed"

echo "Applying Migrations.."
python3 manage.py migrate --noinput

echo "Migrations Completed.."

echo "==== Build Steps Completed ====="
