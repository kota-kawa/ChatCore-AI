#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ID="${$}"
SOURCE_VOLUME="chatcore_pg15_guard_source_${TEST_ID}"
TARGET_VOLUME="chatcore_pg18_guard_target_${TEST_ID}"
TARGET_CONTAINER="chatcore_pg18_guard_target_${TEST_ID}"

cleanup() {
  docker rm -f "${TARGET_CONTAINER}" "chatcore_pg15_guard_init_${TEST_ID}" >/dev/null 2>&1 || true
  docker volume rm -f "${SOURCE_VOLUME}" "${TARGET_VOLUME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

write_volume_file() {
  local volume="$1"
  local path="$2"
  local content="$3"

  docker volume create "${volume}" >/dev/null
  docker run --rm --mount "type=volume,src=${volume},dst=/volume" alpine:3.24.1 \
    sh -ceu 'mkdir -p "$(dirname "/volume/$2")"; printf "%s" "$1" > "/volume/$2"' sh "${content}" "${path}"
}

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

# No source volume is a clean PostgreSQL 18 installation, not a migration.
run_guard

# An unexpected source major must never be opened by the pg15 migration image.
write_volume_file "${SOURCE_VOLUME}" PG_VERSION "14"
if run_guard; then
  echo "Guard accepted an unexpected PostgreSQL source major." >&2
  exit 1
fi

docker volume rm -f "${SOURCE_VOLUME}" >/dev/null
write_volume_file "${SOURCE_VOLUME}" PG_VERSION "15"
write_volume_file "${TARGET_VOLUME}" 18/docker/PG_VERSION "18"

# An existing unmarked target may contain valuable data and must not be overwritten.
if run_guard; then
  echo "Guard accepted an unmarked PostgreSQL 18 target." >&2
  exit 1
fi

# A valid completion marker makes the migration guard safely idempotent.
write_volume_file "${TARGET_VOLUME}" .chatcore-pg15-to-pg18-complete "source_major=15"
run_guard

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

echo "PostgreSQL upgrade guard tests passed."
