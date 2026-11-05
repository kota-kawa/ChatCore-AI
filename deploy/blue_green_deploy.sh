#!/usr/bin/env bash
# [JP] 稼働していない色（blue/green）に新バージョンをデプロイし、nginx の upstream を切り替える本番デプロイ用スクリプト。失敗時は元の色へ戻す。
# [EN] Production deploy script that releases to the inactive color (blue/green) and switches the nginx upstream; it reverts to the old color on failure.
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
CHAT_IMAGE_UPLOAD_VOLUME="${CHAT_IMAGE_UPLOAD_VOLUME:-chatcore-ai_chat_image_uploads}"
PROMPT_SHARE_LEGACY_UPLOAD_DIR="/app/frontend/public/static/uploads/prompt_share"
PROMPT_SHARE_UPLOAD_MIGRATION_MARKER=".legacy_container_migration_complete"
UPLOAD_MIGRATION_IMAGE="alpine:3.24.1"
MIGRATION_SAFETY_BASELINE="${MIGRATION_SAFETY_BASELINE:-20260824_03}"
POST_DEPLOY_CLEANUP_COMMAND="${POST_DEPLOY_CLEANUP_COMMAND:-}"
# [JP] アプリコンテナを非rootで起動するため、Dockerfile の appuser と同じ uid/gid。
# [EN] Must match the appuser uid/gid baked into the Dockerfile.
APP_RUNTIME_UID="${APP_RUNTIME_UID:-10001}"
APP_RUNTIME_GID="${APP_RUNTIME_GID:-10001}"

# [JP] 値が空、または展開されていないシェル変数の名前だけ（例: $FOO）なら真を返す。
# [EN] Return true when the value is empty or just an unexpanded shell variable name such as $FOO.
is_empty_or_unresolved() {
  local value="${1:-}"
  if [ -z "${value}" ]; then
    return 0
  fi

  # [JP] $FOO のような裸のプレースホルダーは無効として扱う。${POSTGRES_DB} のように
  #      波括弧つきの値は、呼び出し側の環境で意図的に展開される場合があるので許可する。
  # [EN] Keep bare shell placeholders as invalid, but allow braced values such as
  #      ${POSTGRES_DB}; they may be intentionally expanded by the caller's env.
  [[ "${value}" =~ ^\$[A-Za-z_][A-Za-z0-9_]*$ ]]
}

# [JP] 必須コマンドが無ければエラーで終了する。
# [EN] Exit with an error when a required command is missing.
require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

# [JP] blue/green 用の Compose ファイルで docker compose を実行する。
# [EN] Run docker compose against the blue/green Compose file.
compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

# [JP] 従来の単一構成（docker-compose.yml）に対して docker compose を実行する。
# [EN] Run docker compose against the legacy single-stack Compose file.
legacy_compose() {
  docker compose --env-file "${ENV_FILE}" -f "${LEGACY_COMPOSE_FILE}" "$@"
}

# [JP] .env が無ければエラーで終了する。
# [EN] Exit with an error when the env file does not exist.
require_env_file() {
  if [ ! -f "${ENV_FILE}" ]; then
    echo "Required env file not found: ${ENV_FILE}" >&2
    exit 1
  fi
}

# [JP] nginx の設定を配置する指定（NGINX_SITE_PATH）があるのに元ファイルが無ければエラーで終了する。
# [EN] Exit with an error when NGINX_SITE_PATH is set but the nginx site source file is missing.
require_nginx_site_source() {
  if [ -n "${NGINX_SITE_PATH}" ] && [ ! -f "${NGINX_SITE_SOURCE}" ]; then
    echo "Required nginx site template not found: ${NGINX_SITE_SOURCE}" >&2
    exit 1
  fi
}

# [JP] .env を読み込み、含まれる変数をすべてエクスポートする。
# [EN] Source the env file and export every variable it defines.
load_env_file() {
  set +u
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
  set -u
}

# [JP] Compose ファイルが解釈できるかを事前に確かめる。
# [EN] Check up front that the Compose file resolves.
preflight_compose_config() {
  compose config >/dev/null
}

# [JP] 必須の環境変数が設定済みかを検査する。MCP が有効なときだけ MCP_OAUTH_ENCRYPTION_KEYS も必須にする。
# [EN] Check that the required environment variables are set; MCP_OAUTH_ENCRYPTION_KEYS is required only when MCP is enabled.
validate_required_env() {
  local required_vars=(
    POSTGRES_DB
    POSTGRES_USER
    POSTGRES_PASSWORD
    REDIS_PASSWORD
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

# [JP] root 以外で実行する場合に、パスワード無しの sudo が使えることを確かめる（途中で止まらないため）。
# [EN] When not running as root, verify passwordless sudo works so the deploy never stalls on a prompt.
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

# [JP] root 権限でコマンドを実行する（root でなければ sudo -n）。
# [EN] Run a command as root (via sudo -n when not already root).
run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

# [JP] 文字列で渡されたシェルコマンドを root 権限で実行する。
# [EN] Run a shell command string as root.
run_root_shell() {
  local command_string="$1"
  if [ "$(id -u)" -eq 0 ]; then
    bash -lc "${command_string}"
  else
    sudo -n bash -lc "${command_string}"
  fi
}

# [JP] ホストの nginx 設定を検査する。NGINX_TEST_CMD があればそれを優先する。
# [EN] Test the host nginx configuration, preferring NGINX_TEST_CMD when set.
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

# [JP] ホストの nginx を reload する。NGINX_RELOAD_CMD、systemctl、nginx -s の順に使える方法を選ぶ。
# [EN] Reload host nginx, choosing NGINX_RELOAD_CMD, then systemctl, then nginx -s.
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

# [JP] blue/green 構成のサービスが healthy になるまで待つ（2 秒間隔）。unhealthy・停止・コンテナ不在、または回数切れで失敗にする。
# [EN] Wait for a blue/green service to become healthy (polling every 2s); fail on unhealthy, stopped or missing containers, or on timeout.
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

# [JP] 従来構成のサービスが healthy になるまで待つ。判定は wait_for_service_healthy と同じ。
# [EN] Wait for a legacy-stack service to become healthy, using the same rules as wait_for_service_healthy.
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

# [JP] 一度きり実行のサービスが終了コード 0 で完了するまで待つ。異常終了や回数切れは失敗にする。
# [EN] Wait for a run-once service to exit with code 0; fail on a non-zero exit or on timeout.
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

# [JP] PostgreSQL が実際にクエリを受け付けるまで待つ（db コンテナ内で SELECT 1 を実行して確認する）。
# [EN] Wait until PostgreSQL actually accepts queries (checked by running SELECT 1 inside the db container).
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

# [JP] 文字列を root 権限でファイルに書き込む。
# [EN] Write a string to a file with root privileges.
write_text_as_root() {
  local target_file="$1"
  local content="$2"

  if [ "$(id -u)" -eq 0 ]; then
    printf "%s" "${content}" > "${target_file}"
  else
    printf "%s" "${content}" | sudo -n tee "${target_file}" >/dev/null
  fi
}

# [JP] 色ごとのホスト側ポート（バックエンド、フロントエンドの順）を返す。blue は 5004/3000、green は 5005/3001。
# [EN] Print the host ports for a color (backend, then frontend): blue is 5004/3000, green is 5005/3001.
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

# [JP] NGINX_SITE_PATH が指定されている場合だけ、nginx のサイト設定を配置する。
# [EN] Install the nginx site config only when NGINX_SITE_PATH is set.
install_nginx_site_config() {
  if [ -n "${NGINX_SITE_PATH}" ]; then
    run_root install -m 644 "${NGINX_SITE_SOURCE}" "${NGINX_SITE_PATH}"
  fi
}

# [JP] 指定した色のポートを指す upstream ファイル（backend_active.conf / frontend_active.conf）を書き出す。nginx はこれで稼働色を切り替える。
# [EN] Write the upstream files (backend_active.conf / frontend_active.conf) pointing at the chosen color's ports; nginx uses them to switch the live color.
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

# [JP] 稼働色の切り替え本体。upstream を書き換えて nginx -t を通し、通ったときだけ reload する。途中で失敗したら元の upstream に戻す。
# [EN] Core of the traffic switch: rewrite the upstreams, pass nginx -t, and reload only then. Any failure restores the previous upstreams.
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

# [JP] デプロイ前に、書き換え後の nginx 設定が通るかを試す。検査に失敗したら upstream を元に戻して失敗にする（実際の切り替えは後で行う）。
# [EN] Before deploying, dry-run whether the rewritten nginx config passes. On failure the upstream files are restored and the script fails;
#      the real traffic switch happens later.
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

# [JP] 現在の稼働色（blue / green / none）を判定する。状態ファイル、nginx の upstream、起動中のコンテナ、従来構成の順に調べる。
# [EN] Detect the live color (blue / green / none), checking the state file, then the nginx upstream, then running containers, then the legacy stack.
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

# [JP] 稼働色の反対の色を返す。none や未知の値のときは blue。
# [EN] Return the opposite color; blue for none or unknown values.
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

# [JP] db・redis と nginx_bootstrap を起動し、準備ができるまで待つ。名前が衝突する他プロジェクトのコンテナや、旧構成の残骸は先に削除する。
# [EN] Start db, redis and nginx_bootstrap and wait until ready. Containers with clashing names owned by another project, and legacy leftovers, are removed first.
start_core_services() {
  local bootstrap_color="${CURRENT_COLOR}"

  if [ "${bootstrap_color}" = "none" ]; then
    bootstrap_color="${TARGET_COLOR}"
  fi

  compose rm -f nginx_bootstrap >/dev/null 2>&1 || true

  # [JP] 名前が衝突するが、この Compose プロジェクト（chatcore-ai）のものではないコンテナを削除する。
  #      旧構成や失敗したデプロイの残骸を片づけるため。このプロジェクトのコンテナは Compose に任せる。
  # [EN] Remove containers with conflicting names that are not owned by this compose
  #      project (chatcore-ai). This handles leftovers from legacy or failed deploys.
  #      Containers already owned by this project are left for compose to manage.
  local cname proj
  for cname in postgres_db redis_cache; do
    proj="$(docker inspect --format='{{index .Config.Labels "com.docker.compose.project"}}' "${cname}" 2>/dev/null || true)"
    if docker inspect "${cname}" >/dev/null 2>&1 && [ "${proj}" != "chatcore-ai" ]; then
      echo "Removing container ${cname} (owner project: '${proj:-none}')" >&2
      docker rm -f "${cname}" >/dev/null 2>&1 || true
    fi
  done

  # [JP] 起動前に、旧構成や孤立したコンテナ（例: fastapi_app、strike_frontend）を削除する。
  #      blue のホストポート（5004/3000）の衝突を防ぐため。
  # [EN] Remove legacy/orphan containers (for example: fastapi_app, strike_frontend)
  #      before bootstrapping to prevent host-port conflicts on blue (5004/3000).
  NGINX_BOOTSTRAP_COLOR="${bootstrap_color}" compose up -d --remove-orphans db redis nginx_bootstrap
  wait_for_service_healthy db 90
  wait_for_postgres_accepting_queries 45
  wait_for_service_healthy redis 90
  wait_for_service_completed nginx_bootstrap 45
}

# [JP] PostgreSQL のメジャーバージョン更新が必要な場合に備え、専用スクリプトを呼ぶ。スクリプトが無い・実行できないときは失敗にする。
# [EN] Call the dedicated script that handles a PostgreSQL major-version upgrade if needed; fail when the script is missing or not executable.
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

# [JP] DB 更新で停止した現行の色（または従来構成）を再起動し、healthy になるまで待つ。後続のビルドが失敗しても元に戻せるようにする。
# [EN] Restart the current color (or legacy stack) stopped by the database upgrade and wait for it to be healthy, so a later build failure can still roll back.
resume_current_color_after_database_upgrade() {
  local color="${CURRENT_COLOR}"

  if [ "${color}" = "none" ]; then
    return 0
  fi

  # [JP] PostgreSQL の一度きりのダンプ/リストアは、DB を使うクライアントをすべて止める。
  #      イメージのビルド前に稼働中のリリースを復帰させ、後のビルド失敗でも正常なアプリへ戻せるようにする。
  # [EN] The one-time PostgreSQL dump/restore stops every database client. Bring the
  #      active release back before image builds so a later build failure can still
  #      roll traffic back to a healthy application.
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

# [JP] 新しい色のアプリとフロントエンドのイメージをビルドする。
# [EN] Build the app and frontend images for the new color.
build_runtime_images() {
  local color="$1"
  compose build "app_${color}" "frontend_${color}"
}

# [JP] マイグレーションの安全性検査を行ってから、後方互換のある事前マイグレーション（Expand）を適用する。
# [EN] Run the migration safety check, then apply the backward-compatible pre-deploy migrations (Expand).
run_migrations() {
  local color="$1"
  echo "Checking migration compatibility against baseline ${MIGRATION_SAFETY_BASELINE}..."
  compose run --rm "app_${color}" \
    python3 scripts/check_migration_safety.py \
    --baseline "${MIGRATION_SAFETY_BASELINE}"
  echo "Running backward-compatible pre-deployment migrations (Expand)..."
  compose run --rm "app_${color}" alembic upgrade head
}

# [JP] 切り替え後の後処理。埋め込みの再生成が必要な行を報告し、POST_DEPLOY_CLEANUP_COMMAND があれば破壊的変更（Contract）として実行する。
# [EN] Post-switch cleanup: report embedding rows needing regeneration and run POST_DEPLOY_CLEANUP_COMMAND (Contract) when configured.
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

# [JP] 指定した色のアプリとフロントエンドを起動し、healthy になるまで待つ。
# [EN] Start the app and frontend of the given color and wait until they are healthy.
deploy_color() {
  local color="$1"
  compose up -d --no-deps "app_${color}" "frontend_${color}"
  wait_for_service_healthy "app_${color}" 90
  wait_for_service_healthy "frontend_${color}" 90
}

# [JP] 指定した色のアプリとフロントエンドを停止して削除する（失敗しても続行）。
# [EN] Stop and remove the app and frontend of the given color, ignoring failures.
stop_color() {
  local color="$1"

  if [ "${color}" = "none" ]; then
    return 0
  fi

  compose stop "app_${color}" "frontend_${color}" >/dev/null 2>&1 || true
  compose rm -f "app_${color}" "frontend_${color}" >/dev/null 2>&1 || true
}

# [JP] 従来構成のアプリとフロントエンドを停止して削除する（失敗しても続行）。
# [EN] Stop and remove the legacy stack's app and frontend, ignoring failures.
stop_legacy_services() {
  if [ ! -f "${LEGACY_COMPOSE_FILE}" ]; then
    return 0
  fi

  legacy_compose stop app frontend >/dev/null 2>&1 || true
  legacy_compose rm -f app frontend >/dev/null 2>&1 || true
}

# [JP] 旧コンテナ内にあったプロンプト共有のアップロードを、永続ボリュームへ上書きせずに移す（完了済みならマーカーで省略）。
# [EN] Move prompt-share uploads from old containers into the persistent volume without overwriting files; skipped once the marker file exists.
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

  # [JP] 稼働中のリリースは、従来の単一サービスか、過去の blue/green のどちらか側かもしれないので、
  #      すべてのアプリ候補を調べる。
  # [EN] Check every app variant because the active release may be a legacy single
  #      service or either side of an earlier blue/green deployment.
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
    # [JP] docker cp は停止中のコンテナの書き込み層も読める。移行元ごとに隔離した一時ディレクトリへ
    #      コピーし、ボリュームには存在しないファイルだけを追加する。
    # [EN] docker cp can read a stopped container's writable layer. Copy each source
    #      into an isolated temp directory, then add only missing files to the volume.
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

# [JP] アップロード用の 3 つのボリューム（プロンプト共有・アバター・チャット画像）の所有権をそろえる。
# [EN] Realign ownership of the three upload volumes (prompt share, avatar, chat image).
ensure_upload_volume_ownership() {
  ensure_volume_ownership "${PROMPT_SHARE_UPLOAD_VOLUME}" "Prompt-share upload" || return 1
  ensure_volume_ownership "${AVATAR_UPLOAD_VOLUME}" "Avatar upload" || return 1
  ensure_volume_ownership "${CHAT_IMAGE_UPLOAD_VOLUME}" "Chat image upload" || return 1
}

# [JP] ここからがメインの流れ。稼働色を判定し、反対の色をデプロイ先に決める。
# [EN] Main flow starts here: detect the live color and pick the opposite one as the deploy target.
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

# [JP] ERR トラップで呼ばれる。切り替え済みなら upstream と状態ファイルを元の色へ戻し、新しい色を停止して、元の終了コードで終わる。
# [EN] Called by the ERR trap: if traffic was switched, restore the upstream and state file to the previous color, stop the new color, and exit with the original code.
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
# [JP] デプロイの順序: nginx の事前検査、アップロードの移行、DB 更新、基盤サービス起動、ビルド、マイグレーション、
#      アップロードボリュームの所有権調整、新色の起動、トラフィック切り替え。
# [EN] Deploy order: nginx preflight, upload migration, DB upgrade, core services, build, migrations,
#      upload-volume ownership, start new color, switch traffic.
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

# [JP] 旧色を停止する。
# [EN] Stop the old color.
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
