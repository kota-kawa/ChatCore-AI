#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.bluegreen.yml}"
LEGACY_COMPOSE_FILE="${LEGACY_COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${ENV_FILE:-.env}"
STATE_FILE="${DEPLOY_STATE_FILE:-.deploy-active-color}"
NGINX_UPSTREAM_DIR="${NGINX_UPSTREAM_DIR:-/etc/nginx/chatcore-ai/upstreams}"
NGINX_SITE_PATH="${NGINX_SITE_PATH:-}"
NGINX_SITE_SOURCE="${NGINX_SITE_SOURCE:-deploy/chatcore-ai.conf}"
NGINX_TEST_CMD="${NGINX_TEST_CMD:-}"
NGINX_RELOAD_CMD="${NGINX_RELOAD_CMD:-}"
DEPLOY_TARGET_COLOR="${DEPLOY_TARGET_COLOR:-}"
PROMPT_SHARE_UPLOAD_VOLUME="${PROMPT_SHARE_UPLOAD_VOLUME:-chatcore-ai_prompt_share_uploads}"
AVATAR_UPLOAD_VOLUME="${AVATAR_UPLOAD_VOLUME:-chatcore-ai_avatar_uploads}"
PROMPT_SHARE_LEGACY_UPLOAD_DIR="/app/frontend/public/static/uploads/prompt_share"
PROMPT_SHARE_UPLOAD_MIGRATION_MARKER=".legacy_container_migration_complete"
UPLOAD_MIGRATION_IMAGE="alpine:3.24.1"
MIGRATION_SAFETY_BASELINE="${MIGRATION_SAFETY_BASELINE:-20260824_03}"
POST_DEPLOY_CLEANUP_COMMAND="${POST_DEPLOY_CLEANUP_COMMAND:-}"
# [JP] アプリコンテナを非rootで起動するため、Dockerfile の appuser と同じ uid/gid。
# [EN] Must match the appuser uid/gid baked into the Dockerfile.
APP_RUNTIME_UID="${APP_RUNTIME_UID:-10001}"
APP_RUNTIME_GID="${APP_RUNTIME_GID:-10001}"

is_empty_or_unresolved() {
  local value="${1:-}"
  if [ -z "${value}" ]; then
    return 0
  fi

  # Keep bare shell placeholders as invalid, but allow braced values such as
  # ${POSTGRES_DB}; they may be intentionally expanded by the caller's env.
  [[ "${value}" =~ ^\$[A-Za-z_][A-Za-z0-9_]*$ ]]
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

legacy_compose() {
  docker compose --env-file "${ENV_FILE}" -f "${LEGACY_COMPOSE_FILE}" "$@"
}

require_env_file() {
  if [ ! -f "${ENV_FILE}" ]; then
    echo "Required env file not found: ${ENV_FILE}" >&2
    exit 1
  fi
}

require_nginx_site_source() {
  if [ -n "${NGINX_SITE_PATH}" ] && [ ! -f "${NGINX_SITE_SOURCE}" ]; then
    echo "Required nginx site template not found: ${NGINX_SITE_SOURCE}" >&2
    exit 1
  fi
}

load_env_file() {
  set +u
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
  set -u
}

preflight_compose_config() {
  compose config >/dev/null
}

validate_required_env() {
  local required_vars=(
    POSTGRES_DB
    POSTGRES_USER
    POSTGRES_PASSWORD
    FASTAPI_SECRET_KEY
  )
  local mcp_enabled="${MCP_ENABLED:-false}"
  local var_name value missing=0

  if [[ "${mcp_enabled,,}" =~ ^(1|true|yes|on)$ ]]; then
    required_vars+=(MCP_OAUTH_ENCRYPTION_KEYS)
  fi

  for var_name in "${required_vars[@]}"; do
    value="${!var_name:-}"
    if is_empty_or_unresolved "${value}"; then
      echo "Required environment variable is empty or unresolved: ${var_name}" >&2
      missing=1
    fi
  done

  if [ "${missing}" -ne 0 ]; then
    exit 1
  fi
}

require_noninteractive_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    return 0
  fi

  require_cmd sudo
  if ! sudo -n true >/dev/null 2>&1; then
    echo "Passwordless sudo is required for non-interactive deploy steps." >&2
    echo "Grant the deploy user sudo NOPASSWD for nginx/install operations or run as root." >&2
    exit 1
  fi
}

require_cmd docker
require_env_file
require_nginx_site_source
load_env_file
preflight_compose_config
validate_required_env
require_noninteractive_sudo

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

run_root_shell() {
  local command_string="$1"
  if [ "$(id -u)" -eq 0 ]; then
    bash -lc "${command_string}"
  else
    sudo -n bash -lc "${command_string}"
  fi
}

nginx_test() {
  if [ -n "${NGINX_TEST_CMD}" ]; then
    run_root_shell "${NGINX_TEST_CMD}"
    return
  fi

  if command -v nginx >/dev/null 2>&1; then
    run_root nginx -t
    return
  fi

  run_root /usr/sbin/nginx -t
}

nginx_reload() {
  if [ -n "${NGINX_RELOAD_CMD}" ]; then
    run_root_shell "${NGINX_RELOAD_CMD}"
    return
  fi

  if command -v systemctl >/dev/null 2>&1; then
    run_root systemctl reload nginx
    return
  fi

  if command -v nginx >/dev/null 2>&1; then
    run_root nginx -s reload
    return
  fi

  run_root /usr/sbin/nginx -s reload
}

wait_for_service_healthy() {
  local service="$1"
  local retries="${2:-90}"
  local cid status

  while [ "${retries}" -gt 0 ]; do
    cid="$(compose ps -a -q "${service}" || true)"
    if [ -z "${cid}" ]; then
      echo "Service ${service} container is missing." >&2
      return 1
    fi

    status="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${cid}")"
    if [ "${status}" = "healthy" ]; then
      echo "Service ${service} is healthy."
      return 0
    fi

    if [ "${status}" = "unhealthy" ] || [ "${status}" = "exited" ] || [ "${status}" = "dead" ]; then
      echo "Service ${service} is ${status}." >&2
      return 1
    fi

    sleep 2
    retries=$((retries - 1))
  done

  echo "Timed out waiting for ${service} to become healthy." >&2
  return 1
}

wait_for_legacy_service_healthy() {
  local service="$1"
  local retries="${2:-90}"
  local cid status

  while [ "${retries}" -gt 0 ]; do
    cid="$(legacy_compose ps -a -q "${service}" || true)"
    if [ -z "${cid}" ]; then
      echo "Legacy service ${service} container is missing." >&2
      return 1
    fi

    status="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${cid}")"
    if [ "${status}" = "healthy" ]; then
      echo "Legacy service ${service} is healthy."
      return 0
    fi
    if [ "${status}" = "unhealthy" ] || [ "${status}" = "exited" ] || [ "${status}" = "dead" ]; then
      echo "Legacy service ${service} is ${status}." >&2
      return 1
    fi

    sleep 2
    retries=$((retries - 1))
  done

  echo "Timed out waiting for legacy ${service} to become healthy." >&2
  return 1
}

wait_for_service_completed() {
  local service="$1"
  local retries="${2:-45}"
  local cid status exit_code

  while [ "${retries}" -gt 0 ]; do
    cid="$(compose ps -a -q "${service}" || true)"
    if [ -z "${cid}" ]; then
      echo "Service ${service} container is missing." >&2
      return 1
    fi

    status="$(docker inspect --format='{{.State.Status}}' "${cid}")"
    case "${status}" in
      exited)
        exit_code="$(docker inspect --format='{{.State.ExitCode}}' "${cid}")"
        if [ "${exit_code}" = "0" ]; then
          echo "Service ${service} completed successfully."
          return 0
        fi
        echo "Service ${service} exited with code ${exit_code}." >&2
        return 1
        ;;
      dead)
        echo "Service ${service} is ${status}." >&2
        return 1
        ;;
    esac

    sleep 1
    retries=$((retries - 1))
  done

  echo "Timed out waiting for ${service} to complete." >&2
  return 1
}

wait_for_postgres_accepting_queries() {
  local retries="${1:-45}"
  local result

  while [ "${retries}" -gt 0 ]; do
    result="$(
      compose exec -T db sh -ceu \
        'PGPASSWORD="${POSTGRES_PASSWORD}" psql -h 127.0.0.1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 -Atc "SELECT 1"' \
        2>/dev/null || true
    )"
    if [ "${result}" = "1" ]; then
      echo "PostgreSQL is accepting queries."
      return 0
    fi

    sleep 2
    retries=$((retries - 1))
  done

  echo "Timed out waiting for PostgreSQL to accept queries." >&2
  return 1
}

write_text_as_root() {
  local target_file="$1"
  local content="$2"

  if [ "$(id -u)" -eq 0 ]; then
    printf "%s" "${content}" > "${target_file}"
  else
    printf "%s" "${content}" | sudo -n tee "${target_file}" >/dev/null
  fi
}

resolve_color_ports() {
  local color="$1"

  case "${color}" in
    blue)
      printf "%s %s\n" "5004" "3000"
      ;;
    green)
      printf "%s %s\n" "5005" "3001"
      ;;
    *)
      echo "Unsupported color: ${color}" >&2
      return 1
      ;;
  esac
}

install_nginx_site_config() {
  if [ -n "${NGINX_SITE_PATH}" ]; then
    run_root install -m 644 "${NGINX_SITE_SOURCE}" "${NGINX_SITE_PATH}"
  fi
}

write_upstream_files() {
  local color="$1"
  local backend_port frontend_port extra ports

  if ! ports="$(resolve_color_ports "${color}")"; then
    return 1
  fi
  read -r backend_port frontend_port extra <<< "${ports}"
  if [ -z "${backend_port}" ] || [ -z "${frontend_port}" ] || [ -n "${extra:-}" ]; then
    echo "Failed to resolve exactly two ports for color: ${color}" >&2
    return 1
  fi

  run_root install -d -m 755 "${NGINX_UPSTREAM_DIR}"

  write_text_as_root "${NGINX_UPSTREAM_DIR}/backend_active.conf" "server 127.0.0.1:${backend_port};"$'\n'
  write_text_as_root "${NGINX_UPSTREAM_DIR}/frontend_active.conf" "server 127.0.0.1:${frontend_port};"$'\n'
}

UPSTREAM_FILE_NAMES=(backend_active.conf frontend_active.conf)
UPSTREAM_BACKUP_DIR=""

discard_upstream_backup() {
  if [ -n "${UPSTREAM_BACKUP_DIR}" ] && [ -d "${UPSTREAM_BACKUP_DIR}" ]; then
    rm -rf "${UPSTREAM_BACKUP_DIR}"
  fi
  UPSTREAM_BACKUP_DIR=""
}

# [JP] upstream ファイルを書き換える前の内容を退避する。
# [EN] Snapshot the current upstream files before they are rewritten.
capture_upstream_backup() {
  local name

  discard_upstream_backup
  UPSTREAM_BACKUP_DIR="$(mktemp -d)"
  for name in "${UPSTREAM_FILE_NAMES[@]}"; do
    if [ -f "${NGINX_UPSTREAM_DIR}/${name}" ]; then
      cp "${NGINX_UPSTREAM_DIR}/${name}" "${UPSTREAM_BACKUP_DIR}/${name}"
    fi
  done
}

# [JP] 書き換えに失敗したときは必ず元の upstream ファイルへ戻す。
# [EN] Always put the previous upstream files back when a rewrite fails.
restore_upstream_backup() {
  local name

  if [ -z "${UPSTREAM_BACKUP_DIR}" ] || [ ! -d "${UPSTREAM_BACKUP_DIR}" ]; then
    return 0
  fi

  for name in "${UPSTREAM_FILE_NAMES[@]}"; do
    if [ -f "${UPSTREAM_BACKUP_DIR}/${name}" ]; then
      run_root install -m 644 "${UPSTREAM_BACKUP_DIR}/${name}" "${NGINX_UPSTREAM_DIR}/${name}" || true
    else
      run_root rm -f "${NGINX_UPSTREAM_DIR}/${name}" || true
    fi
  done

  discard_upstream_backup
}

write_active_upstreams() {
  local color="$1"

  capture_upstream_backup

  if ! write_upstream_files "${color}"; then
    restore_upstream_backup
    return 1
  fi

  if ! install_nginx_site_config; then
    restore_upstream_backup
    return 1
  fi

  # [JP] nginx -t が落ちた時点で書き換え済みファイルを残すと、次の reload で
  #      停止済みの色へトラフィックが流れる。必ず元へ戻してから失敗させる。
  # [EN] Leaving a rewritten upstream file behind after a failed nginx -t would
  #      send traffic to a stopped color on the next reload, so restore first.
  if ! nginx_test; then
    echo "nginx -t failed after pointing upstreams at ${color}; restoring the previous upstream files." >&2
    restore_upstream_backup
    if ! nginx_test; then
      echo "Host Nginx configuration is still invalid after restoring the previous upstreams." >&2
    fi
    return 1
  fi

  discard_upstream_backup
  nginx_reload
}

preflight_nginx_config() {
  local color="$1"

  echo "Checking host Nginx configuration before deployment..."
  capture_upstream_backup
  if ! write_upstream_files "${color}"; then
    restore_upstream_backup
    return 1
  fi
  if [ -n "${NGINX_SITE_PATH}" ]; then
    if ! install_nginx_site_config; then
      restore_upstream_backup
      return 1
    fi
  else
    echo "NGINX_SITE_PATH is unset; validating the existing host Nginx configuration." >&2
  fi

  if ! nginx_test; then
    echo "Host Nginx configuration test failed before application deployment." >&2
    echo "Fix the nginx -t error on the server, then rerun deployment." >&2
    restore_upstream_backup
    return 1
  fi

  discard_upstream_backup
}

detect_active_color() {
  local color

  if [ -f "${STATE_FILE}" ]; then
    read -r color < "${STATE_FILE}" || true
    case "${color}" in
      blue|green)
        echo "${color}"
        return
        ;;
    esac
  fi

  if [ -f "${NGINX_UPSTREAM_DIR}/backend_active.conf" ]; then
    if grep -q "127.0.0.1:5005" "${NGINX_UPSTREAM_DIR}/backend_active.conf"; then
      echo "green"
      return
    fi
    if grep -q "127.0.0.1:5004" "${NGINX_UPSTREAM_DIR}/backend_active.conf"; then
      echo "blue"
      return
    fi
  fi

  if [ -n "$(compose ps -q app_green || true)" ]; then
    echo "green"
    return
  fi

  if [ -n "$(compose ps -q app_blue || true)" ]; then
    echo "blue"
    return
  fi

  if [ -f "${LEGACY_COMPOSE_FILE}" ] && [ -n "$(legacy_compose ps -q app || true)" ]; then
    echo "blue"
    return
  fi

  echo "none"
}

next_color() {
  case "$1" in
    blue)
      echo "green"
      ;;
    green)
      echo "blue"
      ;;
    *)
      echo "blue"
      ;;
  esac
}

start_core_services() {
  local bootstrap_color="${CURRENT_COLOR}"

  if [ "${bootstrap_color}" = "none" ]; then
    bootstrap_color="${TARGET_COLOR}"
  fi

  compose rm -f nginx_bootstrap >/dev/null 2>&1 || true

  # Remove containers with conflicting names that are not owned by this compose
  # project (chatcore-ai). This handles leftovers from legacy or failed deploys.
  # Containers already owned by this project are left for compose to manage.
  local cname proj
  for cname in postgres_db redis_cache; do
    proj="$(docker inspect --format='{{index .Config.Labels "com.docker.compose.project"}}' "${cname}" 2>/dev/null || true)"
    if docker inspect "${cname}" >/dev/null 2>&1 && [ "${proj}" != "chatcore-ai" ]; then
      echo "Removing container ${cname} (owner project: '${proj:-none}')" >&2
      docker rm -f "${cname}" >/dev/null 2>&1 || true
    fi
  done

  # Remove legacy/orphan containers (for example: fastapi_app, strike_frontend)
  # before bootstrapping to prevent host-port conflicts on blue (5004/3000).
  NGINX_BOOTSTRAP_COLOR="${bootstrap_color}" compose up -d --remove-orphans db redis nginx_bootstrap
  wait_for_service_healthy db 90
  wait_for_postgres_accepting_queries 45
  wait_for_service_healthy redis 90
  wait_for_service_completed nginx_bootstrap 45
}

upgrade_postgres_if_required() {
  local upgrade_script="deploy/migrate_postgres_15_to_18.sh"

  if [ ! -x "${upgrade_script}" ]; then
    echo "Required PostgreSQL upgrade guard is missing or not executable: ${upgrade_script}" >&2
    return 1
  fi

  COMPOSE_FILE="${COMPOSE_FILE}" \
    LEGACY_COMPOSE_FILE="${LEGACY_COMPOSE_FILE}" \
    ENV_FILE="${ENV_FILE}" \
    "${upgrade_script}"
}

resume_current_color_after_database_upgrade() {
  local color="${CURRENT_COLOR}"

  if [ "${color}" = "none" ]; then
    return 0
  fi

  # The one-time PostgreSQL dump/restore stops every database client. Bring the
  # active release back before image builds so a later build failure can still
  # roll traffic back to a healthy application.
  if [ -n "$(compose ps -a -q "app_${color}" || true)" ]; then
    compose start "app_${color}" "frontend_${color}"
    wait_for_service_healthy "app_${color}" 90
    wait_for_service_healthy "frontend_${color}" 90
    return 0
  fi

  if [ -f "${LEGACY_COMPOSE_FILE}" ] && [ -n "$(legacy_compose ps -a -q app || true)" ]; then
    legacy_compose start app frontend
    wait_for_legacy_service_healthy app 90
    wait_for_legacy_service_healthy frontend 90
  fi
}

build_runtime_images() {
  local color="$1"
  compose build "app_${color}" "frontend_${color}"
}

run_migrations() {
  local color="$1"
  echo "Checking migration compatibility against baseline ${MIGRATION_SAFETY_BASELINE}..."
  compose run --rm "app_${color}" \
    python3 scripts/check_migration_safety.py \
    --baseline "${MIGRATION_SAFETY_BASELINE}"
  echo "Running backward-compatible pre-deployment migrations (Expand)..."
  compose run --rm "app_${color}" alembic upgrade head
}

run_post_deploy_cleanup() {
  local color="$1"
  # [JP] トラフィック切替と旧バージョンの停止が完了した後に実行する破壊的変更用。
  # [EN] Destructive changes (Contract) to be run after traffic switch and old version stop.
  echo "Checking for post-deployment cleanup migrations (Contract)..."
  echo "Reporting embedding rows that still need regeneration..."
  compose run --rm "app_${color}" \
    python3 scripts/backfill_embeddings.py --dry-run

  if [ -z "${POST_DEPLOY_CLEANUP_COMMAND}" ]; then
    echo "No post-deployment Contract command configured."
    return 0
  fi

  echo "Running configured post-deployment Contract command..."
  compose run --rm "app_${color}" \
    sh -ceu "${POST_DEPLOY_CLEANUP_COMMAND}"
}

deploy_color() {
  local color="$1"
  compose up -d --no-deps "app_${color}" "frontend_${color}"
  wait_for_service_healthy "app_${color}" 90
  wait_for_service_healthy "frontend_${color}" 90
}

stop_color() {
  local color="$1"

  if [ "${color}" = "none" ]; then
    return 0
  fi

  compose stop "app_${color}" "frontend_${color}" >/dev/null 2>&1 || true
  compose rm -f "app_${color}" "frontend_${color}" >/dev/null 2>&1 || true
}

stop_legacy_services() {
  if [ ! -f "${LEGACY_COMPOSE_FILE}" ]; then
    return 0
  fi

  legacy_compose stop app frontend >/dev/null 2>&1 || true
  legacy_compose rm -f app frontend >/dev/null 2>&1 || true
}

migrate_legacy_prompt_share_uploads() {
  local volume_name="${PROMPT_SHARE_UPLOAD_VOLUME}"
  local marker="${PROMPT_SHARE_UPLOAD_MIGRATION_MARKER}"
  local migration_tmp candidate_id candidate_key
  local -a candidate_ids=()
  local -A seen_ids=()

  if [[ ! "${volume_name}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "Invalid prompt-share upload volume name: ${volume_name}" >&2
    return 1
  fi

  docker volume create "${volume_name}" >/dev/null
  if docker run --rm \
    --mount "type=volume,src=${volume_name},dst=/uploads" \
    "${UPLOAD_MIGRATION_IMAGE}" \
    test -f "/uploads/${marker}"; then
    echo "Prompt-share upload volume migration already completed."
    return 0
  fi

  # Check every app variant because the active release may be a legacy single
  # service or either side of an earlier blue/green deployment.
  for candidate_key in app_blue app_green; do
    candidate_id="$(compose ps -a -q "${candidate_key}" 2>/dev/null || true)"
    if [ -n "${candidate_id}" ] && [ -z "${seen_ids[${candidate_id}]:-}" ]; then
      candidate_ids+=("${candidate_id}")
      seen_ids["${candidate_id}"]=1
    fi
  done
  if [ -f "${LEGACY_COMPOSE_FILE}" ]; then
    candidate_id="$(legacy_compose ps -a -q app 2>/dev/null || true)"
    if [ -n "${candidate_id}" ] && [ -z "${seen_ids[${candidate_id}]:-}" ]; then
      candidate_ids+=("${candidate_id}")
      seen_ids["${candidate_id}"]=1
    fi
  fi
  for candidate_key in fastapi_app chatcore_app_blue chatcore_app_green; do
    candidate_id="$(docker inspect --format='{{.Id}}' "${candidate_key}" 2>/dev/null || true)"
    if [ -n "${candidate_id}" ] && [ -z "${seen_ids[${candidate_id}]:-}" ]; then
      candidate_ids+=("${candidate_id}")
      seen_ids["${candidate_id}"]=1
    fi
  done

  migration_tmp="$(mktemp -d)"
  for candidate_id in "${candidate_ids[@]}"; do
    # docker cp can read a stopped container's writable layer. Copy each source
    # into an isolated temp directory, then add only missing files to the volume.
    if docker cp \
      "${candidate_id}:${PROMPT_SHARE_LEGACY_UPLOAD_DIR}/." \
      "${migration_tmp}/" >/dev/null 2>&1; then
      if ! docker run --rm \
          --mount "type=bind,src=${migration_tmp},dst=/legacy,readonly" \
          --mount "type=volume,src=${volume_name},dst=/uploads" \
          "${UPLOAD_MIGRATION_IMAGE}" \
          sh -ceu 'cp -a -n /legacy/. /uploads/'; then
        find "${migration_tmp}" -mindepth 1 -delete
        rmdir "${migration_tmp}"
        return 1
      fi
      find "${migration_tmp}" -mindepth 1 -delete
    fi
  done
  rmdir "${migration_tmp}"

  docker run --rm \
    --mount "type=volume,src=${volume_name},dst=/uploads" \
    "${UPLOAD_MIGRATION_IMAGE}" \
    touch "/uploads/${marker}"
  echo "Prompt-share legacy uploads were migrated without overwriting persistent files."
}

# [JP] アップロードボリュームは root 所有のまま作られている場合があるので、
#      非root実行のアプリが書き込めるよう毎回所有権を揃える。新しく追加した
#      ボリュームも、手動作成や旧デプロイの残骸で root 所有になりうるため同じ扱い。
# [EN] An upload volume can exist root-owned (it may predate the non-root switch
#      or have been created by hand), so realign ownership on every deploy or
#      uploads would start failing. New volumes go through the same path.
ensure_volume_ownership() {
  local volume_name="${1}"
  local label="${2}"

  if [[ ! "${volume_name}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "Invalid ${label} volume name: ${volume_name}" >&2
    return 1
  fi

  docker volume create "${volume_name}" >/dev/null
  docker run --rm \
    --mount "type=volume,src=${volume_name},dst=/uploads" \
    "${UPLOAD_MIGRATION_IMAGE}" \
    chown -R "${APP_RUNTIME_UID}:${APP_RUNTIME_GID}" /uploads
  echo "${label} volume is owned by ${APP_RUNTIME_UID}:${APP_RUNTIME_GID}."
}

ensure_upload_volume_ownership() {
  ensure_volume_ownership "${PROMPT_SHARE_UPLOAD_VOLUME}" "Prompt-share upload" || return 1
  ensure_volume_ownership "${AVATAR_UPLOAD_VOLUME}" "Avatar upload" || return 1
}

CURRENT_COLOR="$(detect_active_color)"
TARGET_COLOR="${DEPLOY_TARGET_COLOR}"

if [ -z "${TARGET_COLOR}" ]; then
  TARGET_COLOR="$(next_color "${CURRENT_COLOR}")"
  if [ "${CURRENT_COLOR}" = "none" ]; then
    TARGET_COLOR="blue"
  fi
fi

if [ "${TARGET_COLOR}" = "${CURRENT_COLOR}" ] && [ "${CURRENT_COLOR}" != "none" ]; then
  echo "Target color matches the active color (${CURRENT_COLOR}). Choose the inactive color instead." >&2
  exit 1
fi

SWITCHED=0

rollback() {
  local exit_code="$?"

  if [ "${SWITCHED}" -eq 1 ] && [ "${CURRENT_COLOR}" != "none" ]; then
    echo "Reverting traffic to ${CURRENT_COLOR}." >&2
    write_active_upstreams "${CURRENT_COLOR}" || true
    printf "%s\n" "${CURRENT_COLOR}" > "${STATE_FILE}" || true
  fi

  stop_color "${TARGET_COLOR}" || true
  exit "${exit_code}"
}

trap rollback ERR

echo "Current color: ${CURRENT_COLOR}"
echo "Deploying inactive color: ${TARGET_COLOR}"

PREFLIGHT_COLOR="${CURRENT_COLOR}"
if [ "${PREFLIGHT_COLOR}" = "none" ]; then
  PREFLIGHT_COLOR="${TARGET_COLOR}"
fi
preflight_nginx_config "${PREFLIGHT_COLOR}"

migrate_legacy_prompt_share_uploads
upgrade_postgres_if_required
start_core_services
resume_current_color_after_database_upgrade
build_runtime_images "${TARGET_COLOR}"
run_migrations "${TARGET_COLOR}"
ensure_upload_volume_ownership
deploy_color "${TARGET_COLOR}"
write_active_upstreams "${TARGET_COLOR}"
printf "%s\n" "${TARGET_COLOR}" > "${STATE_FILE}"
SWITCHED=1

# [JP] ここから先は旧色のコンテナを削除するため、自動ロールバックできない。
#      ERR トラップを解除しないと、後続の失敗で新色まで停止して全断になる。
# [EN] The old color is removed below, so automatic rollback is no longer
#      possible. Disarm the ERR trap here: otherwise a later failure would also
#      stop the new color and take the whole site down.
trap - ERR
echo "Point of no return: automatic rollback is disabled from here on."

if [ "${CURRENT_COLOR}" != "none" ]; then
  stop_color "${CURRENT_COLOR}"
fi

POST_SWITCH_FAILED=0

if ! stop_legacy_services; then
  echo "Failed to stop legacy services after the traffic switch." >&2
  POST_SWITCH_FAILED=1
fi

# [JP] 旧バージョンの停止後、安全に破壊的マイグレーション（カラム削除等）を実行
# [EN] After stopping the old version, safely run destructive migrations (e.g., DROP COLUMN)
if ! run_post_deploy_cleanup "${TARGET_COLOR}"; then
  echo "Post-deployment Contract step failed after the traffic switch." >&2
  echo "The ${TARGET_COLOR} deployment is serving traffic and was left running on purpose." >&2
  echo "Investigate the failure and rerun the Contract step manually." >&2
  POST_SWITCH_FAILED=1
fi

compose ps
echo "Active deployment color: ${TARGET_COLOR}"

if [ "${POST_SWITCH_FAILED}" -ne 0 ]; then
  echo "Traffic switch succeeded but post-switch steps failed; see the errors above." >&2
  exit 1
fi

# [JP] 直近のイメージは即時ロールバックに必要なので、24時間より古いものだけ削除する。
# [EN] Keep recent images so an immediate manual rollback stays possible.
docker system prune -a -f --filter "until=24h" >/dev/null 2>&1 || true
