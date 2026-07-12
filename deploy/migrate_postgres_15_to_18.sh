#!/usr/bin/env bash
set -Eeuo pipefail

# One-time, offline PostgreSQL 15 -> 18 logical migration.
# The legacy volume is never modified or removed. A failed restore removes only
# the incomplete pg18 volume so rerunning this script is safe.

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

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

legacy_compose() {
  docker compose --env-file "${ENV_FILE}" -f "${LEGACY_COMPOSE_FILE}" "$@"
}

volume_exists() {
  docker volume inspect "$1" >/dev/null 2>&1
}

read_volume_file() {
  local volume="$1"
  local path="$2"

  docker run --rm --mount "type=volume,src=${volume},dst=/volume,readonly" \
    "${INSPECT_IMAGE}" sh -ceu 'test -f "/volume/$1" && cat "/volume/$1"' sh "${path}" 2>/dev/null
}

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

stop_database_clients() {
  compose stop app_blue app_green frontend_blue frontend_green >/dev/null 2>&1 || true
  if [ -f "${LEGACY_COMPOSE_FILE}" ]; then
    legacy_compose stop app frontend >/dev/null 2>&1 || true
  fi
  docker rm -f "${TARGET_CONTAINER}" >/dev/null 2>&1 || true
}

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
