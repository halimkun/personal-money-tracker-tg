#!/bin/sh
# Migrasi database dulu (idempoten) sebelum bot mulai.
set -e

alembic upgrade head

exec "$@"
