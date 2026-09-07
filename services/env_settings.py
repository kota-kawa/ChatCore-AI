# 日本語: 環境変数の読み取りと型変換をこのモジュールへ集約し、各サービスでの重複実装を防ぎます。
# English: Centralizes environment-variable reading and coercion so services stop re-implementing it.

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# 日本語: 真値として扱う文字列の集合です。大文字小文字と前後の空白は無視します。
# English: Strings treated as true. Case and surrounding whitespace are ignored.
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


# 日本語: 環境変数を文字列として取得します。未設定と空文字はどちらも未指定として扱います。
# English: Read an environment variable as text, treating both unset and empty as unspecified.
def env_text(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value else default


# 日本語: 環境変数を真偽値として取得します。真値集合に一致しない値はすべて False とみなします。
# English: Read an environment variable as a boolean; anything outside the true set counts as false.
def env_bool(name: str, default: bool = False) -> bool:
    raw = env_text(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUE_VALUES


# 日本語: 解析に失敗した旨を必要に応じて警告ログに出力します。
# English: Optionally record that parsing failed, so misconfiguration is visible in logs.
def _log_invalid_value(name: str, raw: str, default: object, *, warn_on_invalid: bool) -> None:
    if warn_on_invalid:
        logger.warning("Invalid %s value %r. Falling back to %s.", name, raw, default)
    else:
        logger.debug("Invalid %s value %r. Falling back to %s.", name, raw, default)


# 日本語: 環境変数を整数として取得します。解析できない値や minimum 未満の値は既定値へ戻します。
# English: Read an environment variable as an integer, falling back to the default when unparsable or below minimum.
def env_int(name: str, default: int, *, minimum: int | None = 1, warn_on_invalid: bool = False) -> int:
    raw = env_text(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        _log_invalid_value(name, raw, default, warn_on_invalid=warn_on_invalid)
        return default
    if minimum is not None and value < minimum:
        return default
    return value


# 日本語: 環境変数を整数として取得し、範囲外の値は既定値へ戻さず境界値へ丸めます。
# English: Read an integer environment variable and clamp out-of-range values to the bounds instead of falling back.
def env_int_in_range(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int | None = None,
    warn_on_invalid: bool = False,
) -> int:
    raw = env_text(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        _log_invalid_value(name, raw, default, warn_on_invalid=warn_on_invalid)
        return default
    clamped = max(value, minimum)
    if maximum is not None:
        clamped = min(clamped, maximum)
    return clamped


# 日本語: 環境変数を実数として取得します。既定では minimum 以下の値を無効として既定値へ戻します。
# English: Read an environment variable as a float; by default values at or below minimum fall back to the default.
def env_float(
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
    minimum_inclusive: bool = False,
    warn_on_invalid: bool = False,
) -> float:
    raw = env_text(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        _log_invalid_value(name, raw, default, warn_on_invalid=warn_on_invalid)
        return default
    if minimum_inclusive:
        return value if value >= minimum else default
    return value if value > minimum else default
