#!/bin/sh
set -eu

/wait-for-it.sh db:5432 --timeout=60 --strict --

# [JP] 本番環境（Blue/Greenデプロイ）では、デプロイスクリプト側でマイグレーションを制御するため
# コンテナ起動時の自動マイグレーションをスキップします。
# [EN] In production (Blue-Green deployment), skip auto-migrations at startup
# as they are managed by the deployment script.
if [ "${FASTAPI_ENV:-development}" != "production" ]; then
    alembic upgrade head
fi

exec uvicorn app:app --host=0.0.0.0 --port=5004 --proxy-headers --forwarded-allow-ips=*
