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

# [JP] ワーカー数は WEB_CONCURRENCY で制御する（未指定時は 1）。
# チャット状態は Redis に外部化済み（ジョブロック・イベント配信・セッション・レート制限）のため
# 複数ワーカーでも安全に水平スケールできる。
# 注意: ワーカーごとに独立した DB プールを持つため、
#   WEB_CONCURRENCY * DB_POOL_MAX_CONN < Postgres の max_connections を必ず満たすこと。
# [EN] Worker count is controlled by WEB_CONCURRENCY (defaults to 1). Chat state is fully
# externalized to Redis (job locks, event fan-out, sessions, rate limits) so multiple workers
# scale out safely. NOTE: each worker holds its own DB pool, so keep
#   WEB_CONCURRENCY * DB_POOL_MAX_CONN < Postgres max_connections.
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"

exec uvicorn app:app \
    --host=0.0.0.0 \
    --port=5004 \
    --workers "${WEB_CONCURRENCY}" \
    --proxy-headers \
    --forwarded-allow-ips=*
