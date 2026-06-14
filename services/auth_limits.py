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
# Verification-code brute force defence: cap total submit attempts per email
# and per IP across all sessions in a rolling 1-hour window. The previous
# session-scoped attempts counter was bypassable by simply opening a new
# session each round.
DEFAULT_VERIFICATION_ATTEMPT_PER_EMAIL_LIMIT = 10
DEFAULT_VERIFICATION_ATTEMPT_PER_IP_LIMIT = 60
DEFAULT_VERIFICATION_ATTEMPT_WINDOW_SECONDS = 3600
GUEST_CHAT_DAILY_LIMIT_ENV = "GUEST_CHAT_DAILY_LIMIT"
TRUSTED_PROXY_IPS_ENV = "TRUSTED_PROXY_IPS"
DEFAULT_TRUSTED_PROXY_IPS = ("127.0.0.1", "::1")


# 日本語: get positive int env の取得処理を担当します。
# English: Handle fetching for get positive int env.
def _get_positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid %s value %r. Falling back to %s.", name, raw_value, default)
        return default
    return max(parsed, 0)


# 日本語: parse ip address の解析処理を担当します。
# English: Handle parsing for parse ip address.
def _parse_ip_address(raw_value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not isinstance(raw_value, str):
        return None

    value = raw_value.strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not value:
        return None

    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1 and "." in value:
        value = value.rsplit(":", 1)[0]

    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


# 日本語: get trusted proxy networks の取得処理を担当します。
# English: Handle fetching for get trusted proxy networks.
def _get_trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw_value = os.getenv(TRUSTED_PROXY_IPS_ENV)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if raw_value is None:
        raw_entries = DEFAULT_TRUSTED_PROXY_IPS
    else:
        raw_entries = tuple(entry.strip() for entry in raw_value.split(","))

    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for entry in raw_entries:
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid trusted proxy entry %r.", entry)

    return tuple(networks)


# 日本語: is trusted proxy ip に関する処理の入口です。
# English: Entry point for logic related to is trusted proxy ip.
def _is_trusted_proxy_ip(
    client_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    trusted_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    return any(client_ip in network for network in trusted_networks)


# 日本語: get forwarded for ips の取得処理を担当します。
# English: Handle fetching for get forwarded for ips.
def _get_forwarded_for_ips(header_value: str | None) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not isinstance(header_value, str):
        return []

    forwarded_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for raw_part in header_value.split(","):
        parsed_ip = _parse_ip_address(raw_part)
        if parsed_ip is not None:
            forwarded_ips.append(parsed_ip)

    return forwarded_ips


# 日本語: get request client host の取得処理を担当します。
# English: Handle fetching for get request client host.
def _get_request_client_host(request: Request) -> str | None:
    client = getattr(request, "client", None)
    client_host = getattr(client, "host", None)
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if isinstance(client_host, str) and client_host.strip():
        return client_host.strip()
    return None


# 日本語: get request client ip の取得処理を担当します。
# English: Handle fetching for get request client ip.
def get_request_client_ip(request: Request) -> str:
    client_host = _get_request_client_host(request)
    direct_client_ip = _parse_ip_address(client_host)
    trusted_proxy_networks = _get_trusted_proxy_networks()

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
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

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if direct_client_ip is not None:
        return str(direct_client_ip)

    if client_host:
        return client_host

    return "unknown"


# 日本語: hash identifier に関する処理の入口です。
# English: Entry point for logic related to hash identifier.
def _hash_identifier(raw_value: str) -> str:
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


# 日本語: seconds until tomorrow に関する処理の入口です。
# English: Entry point for logic related to seconds until tomorrow.
def _seconds_until_tomorrow() -> int:
    now = datetime.now()
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    seconds = int((tomorrow - now).total_seconds())
    return max(seconds, 1)


# 日本語: get seconds until tomorrow の取得処理を担当します。
# English: Handle fetching for get seconds until tomorrow.
def get_seconds_until_tomorrow() -> int:
    return _seconds_until_tomorrow()


# 日本語: AuthLimitService に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to AuthLimitService.
class AuthLimitService:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(
        self,
        *,
        redis_client_getter: Callable[[], Any | None] | None = None,
    ) -> None:
        self._redis_client_getter = redis_client_getter
        self._in_memory_lock = Lock()
        self._in_memory_windows: dict[str, tuple[int, float]] = {}

    # 日本語: get redis client の取得処理を担当します。
    # English: Handle fetching for get redis client.
    def _get_redis_client(self) -> Any | None:
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if self._redis_client_getter is not None:
            return self._redis_client_getter()
        return get_redis_client()

    # 日本語: reset in memory state に関する処理の入口です。
    # English: Entry point for logic related to reset in memory state.
    def reset_in_memory_state(self) -> None:
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._in_memory_lock:
            self._in_memory_windows.clear()

    # 日本語: consume with redis に関する処理の入口です。
    # English: Entry point for logic related to consume with redis.
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
        # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
        # English: Run potentially failing work in a form that can be caught.
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
            logger.exception("Redis auth rate limiting failed; falling back to in-memory.")
            return None

    # 日本語: consume with in memory に関する処理の入口です。
    # English: Entry point for logic related to consume with in memory.
    def _consume_with_in_memory(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        now = time.monotonic()
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with self._in_memory_lock:
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

            if current >= limit:
                retry_after = max(int(math.ceil(expires_at - now)), 1)
                return False, 0, retry_after

            current += 1
            self._in_memory_windows[key] = (current, expires_at)
            retry_after = max(int(math.ceil(expires_at - now)), 1)
            remaining = max(limit - current, 0)
            return True, remaining, retry_after

    # 日本語: consume rate limit に関する処理の入口です。
    # English: Entry point for logic related to consume rate limit.
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

        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if limit <= 0:
            return False, 0, max(window_seconds, 1)

        redis_client = self._get_redis_client()
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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

    # 日本語: consume guest chat daily limit に関する処理の入口です。
    # English: Entry point for logic related to consume guest chat daily limit.
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
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if allowed:
            return True, None
        return False, f"1日{daily_limit}回までです"

    # 日本語: consume auth email send limits に関する処理の入口です。
    # English: Entry point for logic related to consume auth email send limits.
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

        allowed, _, retry_after = self.consume_rate_limit(
            "auth_email:ip",
            client_ip,
            limit=per_ip_limit,
            window_seconds=window_seconds,
        )
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not allowed:
            return (
                False,
                (
                    "認証メール送信の試行回数が多すぎます。"
                    f"{retry_after}秒ほど待ってから再試行してください。"
                ),
            )

        allowed, _, retry_after = self.consume_rate_limit(
            "auth_email:email",
            normalized_email,
            limit=per_email_limit,
            window_seconds=window_seconds,
        )
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not allowed:
            return (
                False,
                (
                    "このメールアドレスへの認証メール送信が多すぎます。"
                    f"{retry_after}秒ほど待ってから再試行してください。"
                ),
            )

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

    # 日本語: consume admin login limit に関する処理の入口です。
    # English: Entry point for logic related to consume admin login limit.
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
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if allowed:
            return True, None

        return (
            False,
            (
                "管理者ログインの試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
        )

    # 日本語: consume passkey auth options limit に関する処理の入口です。
    # English: Entry point for logic related to consume passkey auth options limit.
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
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if allowed:
            return True, None

        return (
            False,
            (
                "Passkey認証の開始回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
        )

    # 日本語: consume verification attempt limit に関する処理の入口です。
    # English: Entry point for logic related to consume verification attempt limit.
    def consume_verification_attempt_limit(
        self,
        request: Request,
        email: str,
    ) -> tuple[bool, str | None]:
        # Track every verification-code submission attempt per email and per IP
        # across all sessions, so an attacker can't reset the in-session
        # attempts counter by opening a fresh session. Hitting either limit
        # locks further submissions for the rolling window.
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

        allowed, _, retry_after = self.consume_rate_limit(
            "verify_code:email",
            normalized_email or "unknown",
            limit=per_email_limit,
            window_seconds=window_seconds,
        )
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not allowed:
            return (
                False,
                (
                    "認証コードの試行回数が多すぎます。"
                    f"{retry_after}秒ほど待ってから再試行してください。"
                ),
            )

        allowed, _, retry_after = self.consume_rate_limit(
            "verify_code:ip",
            client_ip,
            limit=per_ip_limit,
            window_seconds=window_seconds,
        )
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if not allowed:
            return (
                False,
                (
                    "認証コードの試行回数が多すぎます。"
                    f"{retry_after}秒ほど待ってから再試行してください。"
                ),
            )

        return True, None

    # 日本語: consume passkey auth verify limit に関する処理の入口です。
    # English: Entry point for logic related to consume passkey auth verify limit.
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
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
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


# 日本語: get auth limit service の取得処理を担当します。
# English: Handle fetching for get auth limit service.
def get_auth_limit_service(request: Request = None) -> AuthLimitService:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if request is not None:
        app = request.scope.get("app")
        state = getattr(app, "state", None)
        service = getattr(state, "auth_limit_service", None)
        if isinstance(service, AuthLimitService):
            return service
    return _default_auth_limit_service


# 日本語: clear in memory rate limit state の初期化処理を担当します。
# English: Handle clearing for clear in memory rate limit state.
def clear_in_memory_rate_limit_state() -> None:
    get_auth_limit_service().reset_in_memory_state()


# 日本語: consume rate limit に関する処理の入口です。
# English: Entry point for logic related to consume rate limit.
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


# 日本語: consume guest chat daily limit に関する処理の入口です。
# English: Entry point for logic related to consume guest chat daily limit.
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


# 日本語: consume auth email send limits に関する処理の入口です。
# English: Entry point for logic related to consume auth email send limits.
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


# 日本語: consume admin login limit に関する処理の入口です。
# English: Entry point for logic related to consume admin login limit.
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


# 日本語: consume passkey auth options limit に関する処理の入口です。
# English: Entry point for logic related to consume passkey auth options limit.
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


# 日本語: consume passkey auth verify limit に関する処理の入口です。
# English: Entry point for logic related to consume passkey auth verify limit.
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


# 日本語: consume verification attempt limit に関する処理の入口です。
# English: Entry point for logic related to consume verification attempt limit.
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
