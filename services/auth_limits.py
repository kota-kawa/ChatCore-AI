from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from fastapi import Request

from services.cache import get_redis_client

logger = logging.getLogger(__name__)

# レートリミットに関するデフォルト定数値
# Default constants for rate limits
DEFAULT_AUTH_EMAIL_PER_IP_LIMIT = 10
DEFAULT_AUTH_EMAIL_PER_EMAIL_LIMIT = 5
DEFAULT_AUTH_EMAIL_WINDOW_SECONDS = 600
DEFAULT_AUTH_EMAIL_COOLDOWN_SECONDS = 60
DEFAULT_ADMIN_LOGIN_PER_IP_LIMIT = 10
DEFAULT_ADMIN_LOGIN_WINDOW_SECONDS = 900
DEFAULT_PASSKEY_AUTH_OPTIONS_PER_IP_LIMIT = 30
DEFAULT_PASSKEY_AUTH_VERIFY_PER_IP_LIMIT = 30
DEFAULT_PASSKEY_AUTH_WINDOW_SECONDS = 300
DEFAULT_GUEST_CHAT_DAILY_LIMIT = 10

# 認証コード総当たり攻撃対策用の試行回数上限（ rolling 1-hour window ）
# Total verification attempts cap per email/IP for verification code brute force defense (rolling 1-hour window)
DEFAULT_VERIFICATION_ATTEMPT_PER_EMAIL_LIMIT = 10
DEFAULT_VERIFICATION_ATTEMPT_PER_IP_LIMIT = 60
DEFAULT_VERIFICATION_ATTEMPT_WINDOW_SECONDS = 3600
GUEST_CHAT_DAILY_LIMIT_ENV = "GUEST_CHAT_DAILY_LIMIT"
TRUSTED_PROXY_IPS_ENV = "TRUSTED_PROXY_IPS"
DEFAULT_TRUSTED_PROXY_IPS = ("127.0.0.1", "::1")


# 環境変数から正の整数値を取得するヘルパー関数
# Helper function to get a positive integer from environment variables
def _get_positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        # パースに失敗した場合は警告ログを出力し、デフォルト値を返す
        # If parsing fails, log a warning and return the default value
        logger.warning("Invalid %s value %r. Falling back to %s.", name, raw_value, default)
        return default
    return max(parsed, 0)


# 文字列からIPアドレスオブジェクトを安全に解析・パースする
# Safely parse an IP address object from a string
def _parse_ip_address(raw_value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not isinstance(raw_value, str):
        return None

    value = raw_value.strip()
    if not value:
        return None

    # ブラケットやポート指定を取り除く
    # Remove brackets or port designations
    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1 and "." in value:
        value = value.rsplit(":", 1)[0]

    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


# 信頼されたプロキシサーバーのIPネットワークリストを取得する
# Get the list of trusted proxy IP networks
def _get_trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw_value = os.getenv(TRUSTED_PROXY_IPS_ENV)
    if raw_value is None:
        raw_entries = DEFAULT_TRUSTED_PROXY_IPS
    else:
        raw_entries = tuple(entry.strip() for entry in raw_value.split(","))

    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    # 各エントリーをIPネットワークオブジェクトに変換
    # Convert each entry to an IP network object
    for entry in raw_entries:
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid trusted proxy entry %r.", entry)

    return tuple(networks)


# 指定されたIPアドレスが信頼されたプロキシに含まれているか判定する
# Check if the specified IP address is included in the trusted proxies
def _is_trusted_proxy_ip(
    client_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    trusted_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    return any(client_ip in network for network in trusted_networks)


# X-Forwarded-For ヘッダーからIPアドレスのリストを解析する
# Parse the list of IP addresses from the X-Forwarded-For header
def _get_forwarded_for_ips(header_value: str | None) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    if not isinstance(header_value, str):
        return []

    forwarded_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw_part in header_value.split(","):
        parsed_ip = _parse_ip_address(raw_part)
        if parsed_ip is not None:
            forwarded_ips.append(parsed_ip)

    return forwarded_ips


# Request オブジェクトから直接のクライアントホスト名を取得する
# Get the direct client host string from the Request object
def _get_request_client_host(request: Request) -> str | None:
    client = getattr(request, "client", None)
    client_host = getattr(client, "host", None)
    if isinstance(client_host, str) and client_host.strip():
        return client_host.strip()
    return None


# プロキシを考慮した上で、Request から実際のクライアント IP アドレスを取得する
# Get the real client IP address from the Request, taking proxies into account
def get_request_client_ip(request: Request) -> str:
    client_host = _get_request_client_host(request)
    direct_client_ip = _parse_ip_address(client_host)
    trusted_proxy_networks = _get_trusted_proxy_networks()

    # 直接接続元のIPが信頼済みプロキシの場合、フォワードヘッダーから実際クライアントIPを取り出す
    # If the direct connection IP is a trusted proxy, extract the real client IP from forward headers
    if direct_client_ip is not None and _is_trusted_proxy_ip(
        direct_client_ip,
        trusted_proxy_networks,
    ):
        forwarded_ips = _get_forwarded_for_ips(request.headers.get("x-forwarded-for"))
        for forwarded_ip in reversed(forwarded_ips):
            if not _is_trusted_proxy_ip(forwarded_ip, trusted_proxy_networks):
                return str(forwarded_ip)

        if forwarded_ips:
            return str(forwarded_ips[0])

        real_ip = _parse_ip_address(request.headers.get("x-real-ip"))
        if real_ip is not None:
            return str(real_ip)

    if direct_client_ip is not None:
        return str(direct_client_ip)

    if client_host:
        return client_host

    return "unknown"


# 識別子（IPやメール等）をSHA-256でハッシュ化する（プライバシー保護）
# Hash an identifier (IP, email, etc.) with SHA-256 for privacy protection
def _hash_identifier(raw_value: str) -> str:
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


# 本日の残り秒数（翌日の0:00AMまで）を計算する
# Calculate remaining seconds of today until midnight (tomorrow 0:00AM)
def _seconds_until_tomorrow() -> int:
    now = datetime.now()
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    seconds = int((tomorrow - now).total_seconds())
    return max(seconds, 1)


# 翌日までの残り秒数を取得する外部用ラッパー
# Wrapper function to get remaining seconds until tomorrow
def get_seconds_until_tomorrow() -> int:
    return _seconds_until_tomorrow()


# ユーザー認証やチャットに関するレート制限を処理するサービス
# Service that handles rate limits for user authentication and chats
class AuthLimitService:
    # サービスを初期化する
    # Initialize the service
    def __init__(
        self,
        *,
        redis_client_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self._redis_client_getter = redis_client_getter
        self._in_memory_lock = Lock()
        self._in_memory_windows: dict[str, tuple[int, float]] = {}

    # Redisクライアントを取得する
    # Retrieve the Redis client
    def _get_redis_client(self) -> Any | None:
        if self._redis_client_getter is not None:
            return self._redis_client_getter()
        return get_redis_client()

    # メモリ上のレートリミット用状態データをクリアする
    # Clear the rate limit state stored in memory
    def reset_in_memory_state(self) -> None:
        with self._in_memory_lock:
            self._in_memory_windows.clear()

    # Redisを用いてレート制限の判定と加算をLuaスクリプトでアトミックに実行する
    # Atomically evaluate and increment the rate limit in Redis using a Lua script
    def _consume_with_redis(
        self,
        redis_client: Any,
        redis_key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int, int] | None:
        lua_script = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', key) or '0')
local key_ttl = tonumber(redis.call('TTL', key) or ttl)

if current >= limit then
  if key_ttl < 0 then
    key_ttl = ttl
  end
  return {0, current, key_ttl}
end

current = redis.call('INCR', key)
if current == 1 then
  redis.call('EXPIRE', key, ttl)
  key_ttl = ttl
else
  key_ttl = tonumber(redis.call('TTL', key) or ttl)
  if key_ttl < 0 then
    key_ttl = ttl
  end
end

return {1, current, key_ttl}
"""
        try:
            result = redis_client.eval(lua_script, 1, redis_key, limit, window_seconds)
            if not isinstance(result, (list, tuple)) or len(result) != 3:
                raise ValueError(f"Unexpected Redis rate-limit result: {result}")
            allowed = int(result[0]) == 1
            current = int(result[1])
            retry_after = max(int(result[2]), 1)
            remaining = max(limit - current, 0)
            return allowed, remaining, retry_after
        except Exception:
            # エラー発生時は警告ログを出力し、メモリ上での判定にフォールバックするために None を返す
            # On error, log exception and return None to fall back to in-memory evaluation
            logger.exception("Redis auth rate limiting failed; falling back to in-memory.")
            return None

    # メモリ上でレート制限の判定と加算を行う（スレッドセーフ）
    # Evaluate and increment the rate limit in memory (thread-safe)
    def _consume_with_in_memory(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        now = time.monotonic()
        with self._in_memory_lock:
            # 期限切れのメモリデータを削除する
            # Clean up expired memory records
            expired_keys = [
                existing_key
                for existing_key, (_, expires_at) in self._in_memory_windows.items()
                if expires_at <= now
            ]
            for expired_key in expired_keys:
                self._in_memory_windows.pop(expired_key, None)

            current, expires_at = self._in_memory_windows.get(key, (0, now + window_seconds))
            if expires_at <= now:
                current = 0
                expires_at = now + window_seconds

            # 上限超過時のリトライ待ち時間を計算して返す
            # Calculate and return retry duration if the limit is exceeded
            if current >= limit:
                retry_after = max(int(math.ceil(expires_at - now)), 1)
                return False, 0, retry_after

            current += 1
            self._in_memory_windows[key] = (current, expires_at)
            retry_after = max(int(math.ceil(expires_at - now)), 1)
            remaining = max(limit - current, 0)
            return True, remaining, retry_after

    # レート制限を判定し、消費（インクリメント）する
    # Evaluate and consume (increment) the rate limit
    def consume_rate_limit(
        self,
        key_prefix: str,
        identifier: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        normalized_identifier = (identifier or "").strip().lower() or "unknown"
        redis_key = f"{key_prefix}:{_hash_identifier(normalized_identifier)}"

        if limit <= 0:
            return False, 0, max(window_seconds, 1)

        # Redisが有効な場合はRedisでカウントし、無効な場合や障害時はメモリ上で処理する
        # Try counting with Redis if available; fall back to in-memory on error or unavailability
        redis_client = self._get_redis_client()
        if redis_client is not None:
            redis_result = self._consume_with_redis(
                redis_client,
                redis_key,
                limit=limit,
                window_seconds=window_seconds,
            )
            if redis_result is not None:
                return redis_result

        return self._consume_with_in_memory(
            redis_key,
            limit=limit,
            window_seconds=window_seconds,
        )

    # ゲストユーザー用チャットの1日あたり制限件数を処理する
    # Consume the daily limit for guest user chats
    def consume_guest_chat_daily_limit(self, request: Request) -> tuple[bool, str | None]:
        client_ip = get_request_client_ip(request)
        daily_limit = _get_positive_int_env(
            GUEST_CHAT_DAILY_LIMIT_ENV,
            DEFAULT_GUEST_CHAT_DAILY_LIMIT,
        )
        allowed, _, _ = self.consume_rate_limit(
            "guest_chat:daily:ip",
            client_ip,
            limit=daily_limit,
            window_seconds=_seconds_until_tomorrow(),
        )
        if allowed:
            return True, None
        return False, f"1日{daily_limit}回までです"

    # 認証メールの送信制限を検証・カウントする（IPアドレス・宛先メールアドレスごと）
    # Consume and validate authentication email send limits per IP and email address
    def consume_auth_email_send_limits(self, request: Request, email: str) -> tuple[bool, str | None]:
        client_ip = get_request_client_ip(request)
        normalized_email = (email or "").strip().lower()

        per_ip_limit = _get_positive_int_env(
            "AUTH_EMAIL_PER_IP_LIMIT",
            DEFAULT_AUTH_EMAIL_PER_IP_LIMIT,
        )
        per_email_limit = _get_positive_int_env(
            "AUTH_EMAIL_PER_EMAIL_LIMIT",
            DEFAULT_AUTH_EMAIL_PER_EMAIL_LIMIT,
        )
        window_seconds = _get_positive_int_env(
            "AUTH_EMAIL_WINDOW_SECONDS",
            DEFAULT_AUTH_EMAIL_WINDOW_SECONDS,
        )
        cooldown_seconds = _get_positive_int_env(
            "AUTH_EMAIL_COOLDOWN_SECONDS",
            DEFAULT_AUTH_EMAIL_COOLDOWN_SECONDS,
        )

        # 1. IPアドレスごとの累積上限チェック
        # 1. Cumulative limit check per IP address
        allowed, _, retry_after = self.consume_rate_limit(
            "auth_email:ip",
            client_ip,
            limit=per_ip_limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            return (
                False,
                (
                    "認証メール送信の試行回数が多すぎます。"
                    f"{retry_after}秒ほど待ってから再試行してください。"
                ),
            )

        # 2. メールアドレスごとの累積上限チェック
        # 2. Cumulative limit check per destination email address
        allowed, _, retry_after = self.consume_rate_limit(
            "auth_email:email",
            normalized_email,
            limit=per_email_limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            return (
                False,
                (
                    "このメールアドレスへの認証メール送信が多すぎます。"
                    f"{retry_after}秒ほど待ってから再試行してください。"
                ),
            )

        # 3. 同一メールアドレスへの連続送信防止用クールダウン（1回のみ/クールダウン秒）
        # 3. Cooldown check to prevent consecutive sends to the same email (limit to 1 per cooldown period)
        allowed, _, retry_after = self.consume_rate_limit(
            "auth_email:cooldown",
            normalized_email,
            limit=1,
            window_seconds=cooldown_seconds,
        )
        if not allowed:
            return (
                False,
                (
                    "認証メールは短時間に連続送信できません。"
                    f"{retry_after}秒ほど待ってから再試行してください。"
                ),
            )

        return True, None

    # 管理者ログインの試行制限を処理する
    # Consume the rate limit for administrator logins
    def consume_admin_login_limit(self, request: Request) -> tuple[bool, str | None]:
        client_ip = get_request_client_ip(request)
        per_ip_limit = _get_positive_int_env(
            "ADMIN_LOGIN_PER_IP_LIMIT",
            DEFAULT_ADMIN_LOGIN_PER_IP_LIMIT,
        )
        window_seconds = _get_positive_int_env(
            "ADMIN_LOGIN_WINDOW_SECONDS",
            DEFAULT_ADMIN_LOGIN_WINDOW_SECONDS,
        )

        allowed, _, retry_after = self.consume_rate_limit(
            "admin_login:ip",
            client_ip,
            limit=per_ip_limit,
            window_seconds=window_seconds,
        )
        if allowed:
            return True, None

        return (
            False,
            (
                "管理者ログインの試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
        )

    # Passkeyオプション生成の試行制限を処理する
    # Consume the rate limit for passkey authentication options generation
    def consume_passkey_auth_options_limit(self, request: Request) -> tuple[bool, str | None]:
        client_ip = get_request_client_ip(request)
        per_ip_limit = _get_positive_int_env(
            "PASSKEY_AUTH_OPTIONS_PER_IP_LIMIT",
            DEFAULT_PASSKEY_AUTH_OPTIONS_PER_IP_LIMIT,
        )
        window_seconds = _get_positive_int_env(
            "PASSKEY_AUTH_WINDOW_SECONDS",
            DEFAULT_PASSKEY_AUTH_WINDOW_SECONDS,
        )

        allowed, _, retry_after = self.consume_rate_limit(
            "passkey_auth_options:ip",
            client_ip,
            limit=per_ip_limit,
            window_seconds=window_seconds,
        )
        if allowed:
            return True, None

        return (
            False,
            (
                "Passkey認証の開始回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
        )

    # 認証コード検証の試行制限を検証・カウントする（IPアドレス・宛先メールアドレスごと）
    # Consume and validate verification code submission attempts limit per IP and email
    def consume_verification_attempt_limit(
        self,
        request: Request,
        email: str,
    ) -> tuple[bool, str | None]:
        client_ip = get_request_client_ip(request)
        normalized_email = (email or "").strip().lower()

        per_email_limit = _get_positive_int_env(
            "VERIFICATION_ATTEMPT_PER_EMAIL_LIMIT",
            DEFAULT_VERIFICATION_ATTEMPT_PER_EMAIL_LIMIT,
        )
        per_ip_limit = _get_positive_int_env(
            "VERIFICATION_ATTEMPT_PER_IP_LIMIT",
            DEFAULT_VERIFICATION_ATTEMPT_PER_IP_LIMIT,
        )
        window_seconds = _get_positive_int_env(
            "VERIFICATION_ATTEMPT_WINDOW_SECONDS",
            DEFAULT_VERIFICATION_ATTEMPT_WINDOW_SECONDS,
        )

        # 1. メールアドレスごとの検証試行上限チェック
        # 1. Verification attempts check per email
        allowed, _, retry_after = self.consume_rate_limit(
            "verify_code:email",
            normalized_email or "unknown",
            limit=per_email_limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            return (
                False,
                (
                    "認証コードの試行回数が多すぎます。"
                    f"{retry_after}秒ほど待ってから再試行してください。"
                ),
            )

        # 2. IPアドレスごとの検証試行上限チェック
        # 2. Verification attempts check per IP address
        allowed, _, retry_after = self.consume_rate_limit(
            "verify_code:ip",
            client_ip,
            limit=per_ip_limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            return (
                False,
                (
                    "認証コードの試行回数が多すぎます。"
                    f"{retry_after}秒ほど待ってから再試行してください。"
                ),
            )

        return True, None

    # Passkey検証の試行制限を処理する
    # Consume the rate limit for passkey verification attempts
    def consume_passkey_auth_verify_limit(self, request: Request) -> tuple[bool, str | None]:
        client_ip = get_request_client_ip(request)
        per_ip_limit = _get_positive_int_env(
            "PASSKEY_AUTH_VERIFY_PER_IP_LIMIT",
            DEFAULT_PASSKEY_AUTH_VERIFY_PER_IP_LIMIT,
        )
        window_seconds = _get_positive_int_env(
            "PASSKEY_AUTH_WINDOW_SECONDS",
            DEFAULT_PASSKEY_AUTH_WINDOW_SECONDS,
        )

        allowed, _, retry_after = self.consume_rate_limit(
            "passkey_auth_verify:ip",
            client_ip,
            limit=per_ip_limit,
            window_seconds=window_seconds,
        )
        if allowed:
            return True, None

        return (
            False,
            (
                "Passkey認証の試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
        )


_default_auth_limit_service = AuthLimitService()


# アプリケーション状態や依存関係から適切な AuthLimitService インスタンスを取得する
# Retrieve the appropriate AuthLimitService instance from the application state or defaults
def get_auth_limit_service(request: Request = None) -> AuthLimitService:
    if request is not None:
        app = request.scope.get("app")
        state = getattr(app, "state", None)
        service = getattr(state, "auth_limit_service", None)
        if isinstance(service, AuthLimitService):
            return service
    return _default_auth_limit_service


# メモリ上のレートリミット状態をクリアする
# Clear the in-memory rate limiting state data
def clear_in_memory_rate_limit_state() -> None:
    get_auth_limit_service().reset_in_memory_state()


# レートリミット制限の判定と消費を行う外部用関数
# Function to evaluate and consume the rate limit (external entry point)
def consume_rate_limit(
    key_prefix: str,
    identifier: str,
    *,
    limit: int,
    window_seconds: int,
    service: AuthLimitService | None = None,
) -> tuple[bool, int, int]:
    target = service if isinstance(service, AuthLimitService) else get_auth_limit_service()
    return target.consume_rate_limit(
        key_prefix,
        identifier,
        limit=limit,
        window_seconds=window_seconds,
    )


# ゲストユーザー用のチャット制限を行う外部用関数
# Function to consume the daily limit for guest chats (external entry point)
def consume_guest_chat_daily_limit(
    request: Request,
    *,
    service: AuthLimitService | None = None,
) -> tuple[bool, str | None]:
    target = (
        service
        if isinstance(service, AuthLimitService)
        else get_auth_limit_service(request)
    )
    return target.consume_guest_chat_daily_limit(request)


# 認証メール送信制限の判定・消費を行う外部用関数
# Function to consume authentication email send limits (external entry point)
def consume_auth_email_send_limits(
    request: Request,
    email: str,
    *,
    service: AuthLimitService | None = None,
) -> tuple[bool, str | None]:
    target = (
        service
        if isinstance(service, AuthLimitService)
        else get_auth_limit_service(request)
    )
    return target.consume_auth_email_send_limits(request, email)


# 管理者ログインの試行制限判定・消費を行う外部用関数
# Function to consume admin login limits (external entry point)
def consume_admin_login_limit(
    request: Request,
    *,
    service: AuthLimitService | None = None,
) -> tuple[bool, str | None]:
    target = (
        service
        if isinstance(service, AuthLimitService)
        else get_auth_limit_service(request)
    )
    return target.consume_admin_login_limit(request)


# Passkeyオプション生成の試行制限判定・消費を行う外部用関数
# Function to consume passkey auth options limits (external entry point)
def consume_passkey_auth_options_limit(
    request: Request,
    *,
    service: AuthLimitService | None = None,
) -> tuple[bool, str | None]:
    target = (
        service
        if isinstance(service, AuthLimitService)
        else get_auth_limit_service(request)
    )
    return target.consume_passkey_auth_options_limit(request)


# Passkey認証検証の試行制限判定・消費を行う外部用関数
# Function to consume passkey auth verify limits (external entry point)
def consume_passkey_auth_verify_limit(
    request: Request,
    *,
    service: AuthLimitService | None = None,
) -> tuple[bool, str | None]:
    target = (
        service
        if isinstance(service, AuthLimitService)
        else get_auth_limit_service(request)
    )
    return target.consume_passkey_auth_verify_limit(request)


# 認証コード検証試行回数の制限判定・消費を行う外部用関数
# Function to consume verification code attempts limits (external entry point)
def consume_verification_attempt_limit(
    request: Request,
    email: str,
    *,
    service: AuthLimitService | None = None,
) -> tuple[bool, str | None]:
    target = (
        service
        if isinstance(service, AuthLimitService)
        else get_auth_limit_service(request)
    )
    return target.consume_verification_attempt_limit(request, email)
