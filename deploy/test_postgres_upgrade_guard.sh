#!/usr/bin/env bash
# 移行スクリプト deploy/migrate_postgres_15_to_18.sh のガード判定（移行元の検証、上書き防止、冪等性）を検査するテスト。
# Test for the guard logic of deploy/migrate_postgres_15_to_18.sh (source validation, no-overwrite protection, idempotency).
set -Eeuo pipefail

# 使い捨てのボリューム名とコンテナ名にはプロセスID（$$）を付け、並行実行や過去の実行と衝突しないようにする。
# Disposable volume and container names carry the process ID ($$) so they never clash with parallel or earlier runs.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ID="${$}"
SOURCE_VOLUME="chatcore_pg15_guard_source_${TEST_ID}"
TARGET_VOLUME="chatcore_pg18_guard_target_${TEST_ID}"
TARGET_CONTAINER="chatcore_pg18_guard_target_${TEST_ID}"

# 終了時（成功・失敗を問わず）にテスト用のコンテナとボリュームを削除する。
# On exit (success or failure), remove the test containers and volumes.
cleanup() {
  docker rm -f "${TARGET_CONTAINER}" "chatcore_pg15_guard_init_${TEST_ID}" >/dev/null 2>&1 || true
  docker volume rm -f "${SOURCE_VOLUME}" "${TARGET_VOLUME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ボリューム内の指定パスに、与えた内容のファイルを作る（親ディレクトリも作成する）。
# Create a file with the given content at a path inside a volume, creating parent directories too.
write_volume_file() {
  local volume="$1"
  local path="$2"
  local content="$3"

  docker volume create "${volume}" >/dev/null
  docker run --rm --mount "type=volume,src=${volume},dst=/volume" alpine:3.24.1 \
    sh -ceu 'mkdir -p "$(dirname "/volume/$2")"; printf "%s" "$1" > "/volume/$2"' sh "${content}" "${path}"
}

# 隔離した設定（専用のボリューム名・コンテナ名・Compose プロジェクト名）で本物の移行スクリプトを実行する。
# Run the real migration script with isolated settings (dedicated volume, container and Compose project names).
run_guard() {
  POSTGRES_DB=guard_test \
    POSTGRES_USER=guard_test \
    POSTGRES_PASSWORD=guard_test \
    POSTGRES_15_ARCHIVE_VOLUME="${SOURCE_VOLUME}" \
    POSTGRES_18_VOLUME="${TARGET_VOLUME}" \
    POSTGRES_CONTAINER_NAME="${TARGET_CONTAINER}" \
    COMPOSE_PROJECT_NAME="chatcore-pg-upgrade-test-${TEST_ID}" \
    ENV_FILE=/dev/null \
    "${ROOT_DIR}/deploy/migrate_postgres_15_to_18.sh"
}

# 移行元のボリュームが無ければ、移行ではなく PostgreSQL 18 の新規構築なので成功する。
# No source volume is a clean PostgreSQL 18 installation, not a migration.
run_guard

# 想定外のメジャーバージョンの移行元を、pg15 の移行用イメージで開いてはならない（拒否されるべき）。
# An unexpected source major must never be opened by the pg15 migration image.
write_volume_file "${SOURCE_VOLUME}" PG_VERSION "14"
if run_guard; then
  echo "Guard accepted an unexpected PostgreSQL source major." >&2
  exit 1
fi

docker volume rm -f "${SOURCE_VOLUME}" >/dev/null
write_volume_file "${SOURCE_VOLUME}" PG_VERSION "15"
write_volume_file "${TARGET_VOLUME}" 18/docker/PG_VERSION "18"

# 完了マーカーの無い既存の移行先には大切なデータがあるかもしれないので、上書きしてはならない（拒否されるべき）。
# An existing unmarked target may contain valuable data and must not be overwritten.
if run_guard; then
  echo "Guard accepted an unmarked PostgreSQL 18 target." >&2
  exit 1
fi

# 有効な完了マーカーがあれば、ガードは何もせず成功する（何度実行しても安全）。
# A valid completion marker makes the migration guard safely idempotent.
write_volume_file "${TARGET_VOLUME}" .chatcore-pg15-to-pg18-complete "source_major=15"
run_guard

# 上のガード判定の検査は高速で結果が安定している（小さな alpine のボリュームしか使わない）ため常に実行する。
# 以下の pg15 から pg18 への実際のダンプ/リストアは、数百 MB の PostgreSQL イメージを取得して実コンテナを起動するので、
# CI を速く保ちレジストリの不調の影響を受けないよう任意実行にしている。手元や必要なときに RUN_POSTGRES_MIGRATION_E2E=1 で実行する。
# The guard-logic checks above are fast and deterministic (they only touch
# tiny alpine-backed volumes) and always run. The full pg15 -> pg18 dump/restore
# below pulls multi-hundred-MB PostgreSQL images and starts live containers, so
# it is opt-in to keep CI fast and immune to registry hiccups. Run it locally or
# on demand with RUN_POSTGRES_MIGRATION_E2E=1.
if [ "${RUN_POSTGRES_MIGRATION_E2E:-0}" != "1" ]; then
  echo "PostgreSQL upgrade guard-logic tests passed."
  echo "Skipping full pg15->pg18 dump/restore (set RUN_POSTGRES_MIGRATION_E2E=1 to run it)."
  exit 0
fi

# pgvector のデータを入れた状態で、実際の pg15 から pg18 へのダンプ/リストアの経路を通して確かめる。
# Exercise the real pg15 -> pg18 dump/restore path with pgvector data.
docker volume rm -f "${SOURCE_VOLUME}" "${TARGET_VOLUME}" >/dev/null
docker run -d --name "chatcore_pg15_guard_init_${TEST_ID}" \
  -e POSTGRES_DB=guard_test \
  -e POSTGRES_USER=guard_test \
  -e POSTGRES_PASSWORD=guard_test \
  --mount "type=volume,src=${SOURCE_VOLUME},dst=/var/lib/postgresql/data" \
  pgvector/pgvector:0.8.5-pg15 >/dev/null

retries=60
until docker exec "chatcore_pg15_guard_init_${TEST_ID}" \
  pg_isready -U guard_test -d guard_test >/dev/null 2>&1; do
  retries=$((retries - 1))
  if [ "${retries}" -eq 0 ]; then
    echo "Timed out initializing the PostgreSQL 15 test database." >&2
    exit 1
  fi
  sleep 1
done

docker exec "chatcore_pg15_guard_init_${TEST_ID}" psql -v ON_ERROR_STOP=1 \
  -U guard_test -d guard_test -c \
  "CREATE EXTENSION vector; CREATE TABLE migration_probe (id integer PRIMARY KEY, embedding vector(3)); INSERT INTO migration_probe VALUES (1, '[1,2,3]');" \
  >/dev/null
docker rm -f "chatcore_pg15_guard_init_${TEST_ID}" >/dev/null

run_guard
probe="$(docker exec "${TARGET_CONTAINER}" psql -At -U guard_test -d guard_test -c 'SELECT id FROM migration_probe')"
if [ "${probe}" != "1" ]; then
  echo "Restored PostgreSQL 18 database did not contain the migration probe row." >&2
  exit 1
fi

echo "PostgreSQL upgrade guard tests passed (including full pg15->pg18 dump/restore)."
