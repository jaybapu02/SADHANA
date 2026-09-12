#!/usr/bin/env bash
# build.sh – Render build script for Sadhana 2.0
set -o errexit

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Collect static files for WhiteNoise
python manage.py collectstatic --noinput

# Run database migrations manually via Render Shell after first deploy:
# python manage.py migrate --noinput
