#!/bin/sh
# Migrasi database dulu (idempoten) sebelum bot mulai.
set -e

python -m alembic upgrade head

exec "$@"
