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

# [JP] --proxy-headers を有効にすると uvicorn は X-Forwarded-For からクライアントIPを解決する。
#      ワイルドカード（*）にすると送信元を問わずヘッダー先頭の値をそのまま採用してしまい、
#      per-IP のレート制限が偽装1つで無効化される。信頼する送信元は前段プロキシだけに限定する。
#      既定値はループバックと RFC1918（アプリのポートは 127.0.0.1 にバインドしているため、
#      ホストの nginx からは docker のブリッジ・ゲートウェイ経由で届く）。
#      別構成では FORWARDED_ALLOW_IPS に実際のプロキシIP／CIDRを設定して絞り込むこと。
# [EN] With --proxy-headers uvicorn resolves the client IP from X-Forwarded-For. A wildcard (*)
#      accepts the leading header value from any peer, so a single spoofed header disables the
#      per-IP rate limits. Trust only the fronting proxy. The default covers loopback plus RFC1918,
#      because the app ports are bound to 127.0.0.1 and the host nginx therefore reaches the
#      container through the docker bridge gateway. Override FORWARDED_ALLOW_IPS with the actual
#      proxy IPs/CIDRs for other topologies.
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}"

exec uvicorn app:app \
    --host=0.0.0.0 \
    --port=5004 \
    --workers "${WEB_CONCURRENCY}" \
    --proxy-headers \
    --forwarded-allow-ips="${FORWARDED_ALLOW_IPS}"
