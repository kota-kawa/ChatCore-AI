#!/usr/bin/env bash
# [JP] 一度きり・オフラインで行う PostgreSQL 15 から 18 への論理移行（ダンプとリストア）。
#      deploy/blue_green_deploy.sh から呼ばれる。旧ボリュームは変更も削除もしない。リストアに失敗したら不完全な pg18 ボリュームだけを削除するので、再実行しても安全。
# [EN] One-time, offline PostgreSQL 15 -> 18 logical migration.
#      Called from deploy/blue_green_deploy.sh. The legacy volume is never modified or removed. A failed restore removes only
#      the incomplete pg18 volume so rerunning this script is safe.

set -Eeuo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.bluegreen.yml}"
LEGACY_COMPOSE_FILE="${LEGACY_COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${ENV_FILE:-.env}"
LEGACY_VOLUME="${POSTGRES_15_ARCHIVE_VOLUME:-chatcore-ai_db_data}"
TARGET_VOLUME="${POSTGRES_18_VOLUME:-chatcore-ai_db_data_pg18}"
SOURCE_IMAGE="${POSTGRES_15_IMAGE:-pgvector/pgvector:0.8.5-pg15}"
INSPECT_IMAGE="${POSTGRES_VOLUME_INSPECT_IMAGE:-alpine:3.24.1}"
SOURCE_CONTAINER="chatcore_pg15_upgrade_source"
TARGET_CONTAINER="${POSTGRES_CONTAINER_NAME:-postgres_db}"
MIGRATION_MARKER=".chatcore-pg15-to-pg18-complete"
TARGET_CREATED=0
WORK_DIR=""

# [JP] blue/green 用の Compose ファイルで docker compose を実行する。
# [EN] Run docker compose against the blue/green Compose file.
compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

# [JP] 従来の単一構成の Compose ファイルで docker compose を実行する。
# [EN] Run docker compose against the legacy single-stack Compose file.
legacy_compose() {
  docker compose --env-file "${ENV_FILE}" -f "${LEGACY_COMPOSE_FILE}" "$@"
}

# [JP] 指定した Docker ボリュームが存在するかを返す。
# [EN] Return whether the named Docker volume exists.
volume_exists() {
  docker volume inspect "$1" >/dev/null 2>&1
}

# [JP] ボリューム内のファイルを、読み取り専用でマウントした一時コンテナ越しに読んで出力する（無ければ失敗）。
# [EN] Print a file from a volume through a throwaway container with a read-only mount (fails if the file does not exist).
read_volume_file() {
  local volume="$1"
  local path="$2"

  docker run --rm --mount "type=volume,src=${volume},dst=/volume,readonly" \
    "${INSPECT_IMAGE}" sh -ceu 'test -f "/volume/$1" && cat "/volume/$1"' sh "${path}" 2>/dev/null
}

# [JP] コンテナ内の PostgreSQL が接続を受け付けるまで待つ（2 秒間隔、最大 60 回）。
# [EN] Wait until the PostgreSQL in the container accepts connections (every 2s, up to 60 tries).
wait_for_postgres() {
  local container="$1"
  local retries=60

  while [ "${retries}" -gt 0 ]; do
    if docker exec "${container}" sh -ceu \
      'PGPASSWORD="${POSTGRES_PASSWORD}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"' \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    retries=$((retries - 1))
  done

  echo "Timed out waiting for PostgreSQL container ${container}." >&2
  return 1
}

# [JP] 移行元が単一データベース・単一オーナーであることを確かめる。ほかのユーザーDBや別オーナーのオブジェクトがあると、
#      --no-owner のダンプで失われるので移行を拒否する。
# [EN] Verify the source is a single database with a single owner. Extra user databases or objects owned by other roles
#      would be lost by a --no-owner dump, so the migration is refused.
validate_source_scope() {
  local database_names
  local database_name
  local extra_databases=""
  local foreign_owners

  database_names="$(
    docker exec "${SOURCE_CONTAINER}" sh -ceu \
      'PGPASSWORD="${POSTGRES_PASSWORD}" psql -X -v ON_ERROR_STOP=1 -At -U "${POSTGRES_USER}" -d postgres -c "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate AND datname <> '\''postgres'\'' ORDER BY datname"'
  )"
  while IFS= read -r database_name; do
    if [ -n "${database_name}" ] && [ "${database_name}" != "${POSTGRES_DB}" ]; then
      extra_databases+="${database_name}"$'\n'
    fi
  done <<< "${database_names}"
  if [ -n "${extra_databases}" ]; then
    echo "Refusing single-database migration because additional user databases exist:" >&2
    printf "%s" "${extra_databases}" >&2
    return 1
  fi

  foreign_owners="$(
    docker exec "${SOURCE_CONTAINER}" sh -ceu \
      'PGPASSWORD="${POSTGRES_PASSWORD}" psql -X -v ON_ERROR_STOP=1 -At -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT DISTINCT pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname NOT IN ('\''pg_catalog'\'', '\''information_schema'\'') AND pg_get_userbyid(c.relowner) <> current_user ORDER BY 1"'
  )"
  if [ -n "${foreign_owners}" ]; then
    echo "Refusing --no-owner migration because application objects have other owners:" >&2
    echo "${foreign_owners}" >&2
    return 1
  fi
}

# [JP] 全テーブルの行数を「テーブル名 件数」で出力ファイルへ書く。移行前後で比べて取りこぼしを検出するために使う。
# [EN] Write every table's row count to the destination file; compared before and after the migration to detect missing rows.
snapshot_table_counts() {
  local container="$1"
  local destination="$2"

  docker exec -i "${container}" sh -ceu \
    'PGPASSWORD="${POSTGRES_PASSWORD}" psql -X -v ON_ERROR_STOP=1 -At -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"' \
    > "${destination}" <<'SQL'
SELECT format(
  'SELECT %L, count(*) FROM %I.%I',
  schemaname || '.' || tablename,
  schemaname,
  tablename
)
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, tablename
\gexec
SQL
}

# [JP] DB を使うクライアント（blue/green の app と frontend、従来構成、現行の DB コンテナ）をすべて止める。
# [EN] Stop every database client (blue/green app and frontend, the legacy stack) and the current DB container.
stop_database_clients() {
  compose stop app_blue app_green frontend_blue frontend_green >/dev/null 2>&1 || true
  if [ -f "${LEGACY_COMPOSE_FILE}" ]; then
    legacy_compose stop app frontend >/dev/null 2>&1 || true
  fi
  docker rm -f "${TARGET_CONTAINER}" >/dev/null 2>&1 || true
}

# [JP] EXIT トラップ。一時コンテナと作業ディレクトリを消し、失敗かつ pg18 ボリュームを作成済みなら、その不完全なボリュームだけを削除する。
# [EN] EXIT trap: remove the temporary container and work directory, and on failure delete only the incomplete pg18 volume if it was created.
cleanup() {
  local exit_code="$?"

  docker rm -f "${SOURCE_CONTAINER}" >/dev/null 2>&1 || true
  if [ -n "${WORK_DIR}" ] && [ -d "${WORK_DIR}" ]; then
    rm -rf "${WORK_DIR}"
  fi

  if [ "${exit_code}" -ne 0 ] && [ "${TARGET_CREATED}" -eq 1 ]; then
    echo "Migration failed; removing only the incomplete PostgreSQL 18 volume." >&2
    compose stop db >/dev/null 2>&1 || true
    docker rm -f "${TARGET_CONTAINER}" >/dev/null 2>&1 || true
    docker volume rm "${TARGET_VOLUME}" >/dev/null 2>&1 || true
  fi

  exit "${exit_code}"
}
trap cleanup EXIT

# [JP] ここからがメインの流れ。移行が必要かを確かめる（旧ボリュームの有無、PG_VERSION、移行先の完了マーカー）。
# [EN] Main flow starts here: first decide whether a migration is needed (legacy volume, PG_VERSION, target completion marker).
if ! volume_exists "${LEGACY_VOLUME}"; then
  echo "No PostgreSQL 15 archive volume (${LEGACY_VOLUME}) exists; no upgrade is required."
  exit 0
fi

source_major="$(read_volume_file "${LEGACY_VOLUME}" PG_VERSION || true)"
if [ "${source_major}" != "15" ]; then
  echo "Refusing migration: ${LEGACY_VOLUME} contains PostgreSQL '${source_major:-unknown}', expected 15." >&2
  exit 1
fi

if volume_exists "${TARGET_VOLUME}"; then
  target_major="$(read_volume_file "${TARGET_VOLUME}" 18/docker/PG_VERSION || true)"
  marker="$(read_volume_file "${TARGET_VOLUME}" "${MIGRATION_MARKER}" || true)"
  if [ "${target_major}" = "18" ] && [ -n "${marker}" ]; then
    echo "PostgreSQL 15 -> 18 migration was already completed; archived pg15 volume remains untouched."
    exit 0
  fi

  echo "Refusing to overwrite existing target volume ${TARGET_VOLUME}." >&2
  echo "Its PostgreSQL version is '${target_major:-uninitialized}' and it has no completion marker." >&2
  echo "Inspect it manually; remove only this target volume if it is a failed, disposable migration attempt." >&2
  exit 1
fi

# [JP] 移行本体: pg15 をダンプ（行数も記録）してから、pg18 へリストアし、行数・pgvector のバージョンを検証して完了マーカーを書く。
# [EN] The migration itself: dump pg15 (recording row counts), restore into pg18, verify row counts and the pgvector version, then write the completion marker.
echo "PostgreSQL 15 data detected. Starting one-time offline dump/restore into PostgreSQL 18."
stop_database_clients
WORK_DIR="$(mktemp -d)"
chmod 700 "${WORK_DIR}"

docker rm -f "${SOURCE_CONTAINER}" >/dev/null 2>&1 || true
docker run -d --name "${SOURCE_CONTAINER}" \
  -e POSTGRES_DB -e POSTGRES_USER -e POSTGRES_PASSWORD \
  --mount "type=volume,src=${LEGACY_VOLUME},dst=/var/lib/postgresql/data" \
  "${SOURCE_IMAGE}" >/dev/null
wait_for_postgres "${SOURCE_CONTAINER}"
validate_source_scope

snapshot_table_counts "${SOURCE_CONTAINER}" "${WORK_DIR}/source-counts"
docker exec "${SOURCE_CONTAINER}" sh -ceu \
  'PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --format=custom --no-owner --no-acl' \
  > "${WORK_DIR}/database.dump"
dump_sha256="$(sha256sum "${WORK_DIR}/database.dump" | awk '{print $1}')"
docker rm -f "${SOURCE_CONTAINER}" >/dev/null

TARGET_CREATED=1
compose up -d db
wait_for_postgres "${TARGET_CONTAINER}"
docker exec -i "${TARGET_CONTAINER}" sh -ceu \
  'PGPASSWORD="${POSTGRES_PASSWORD}" pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --clean --if-exists --no-owner --no-acl --exit-on-error' \
  < "${WORK_DIR}/database.dump"

snapshot_table_counts "${TARGET_CONTAINER}" "${WORK_DIR}/target-counts"
if ! diff -u "${WORK_DIR}/source-counts" "${WORK_DIR}/target-counts"; then
  echo "PostgreSQL migration validation failed: table row counts differ." >&2
  exit 1
fi

vector_version="$(
  docker exec "${TARGET_CONTAINER}" sh -ceu \
    'PGPASSWORD="${POSTGRES_PASSWORD}" psql -X -v ON_ERROR_STOP=1 -At -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT extversion FROM pg_extension WHERE extname = '\''vector'\''"'
)"
if [ -n "${vector_version}" ] && [ "${vector_version}" != "0.8.5" ]; then
  echo "Unexpected pgvector extension version after restore: ${vector_version}" >&2
  exit 1
fi

docker exec "${TARGET_CONTAINER}" sh -ceu \
  'PGPASSWORD="${POSTGRES_PASSWORD}" vacuumdb -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --analyze-in-stages' \
  >/dev/null

docker exec "${TARGET_CONTAINER}" sh -ceu \
  'printf "source_major=15\ntarget_major=18\ndump_sha256=%s\ncompleted_at=%s\n" "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "/var/lib/postgresql/$2"' \
  sh "${dump_sha256}" "${MIGRATION_MARKER}"

TARGET_CREATED=0
echo "PostgreSQL 18 restore and exact per-table row-count validation completed."
echo "Legacy volume ${LEGACY_VOLUME} is retained as a read-only rollback archive."
