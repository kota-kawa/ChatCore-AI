#!/bin/sh
set -eu

/wait-for-it.sh db:5432 --timeout=60 --strict --
alembic upgrade head
exec uvicorn app:app --host=0.0.0.0 --port=5004 --proxy-headers --forwarded-allow-ips=*
