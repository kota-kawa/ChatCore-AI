from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from services.request_context import RequestContextFilter

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_DIR = "logs"
DEFAULT_APP_LOG_FILE = "app.log"
DEFAULT_ERROR_LOG_FILE = "error.log"
DEFAULT_LOG_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 10
DEFAULT_LOG_OUTPUT = "json"

APP_LOG_HANDLER_NAME = "chatcore_app_file"
ERROR_LOG_HANDLER_NAME = "chatcore_error_file"
CONSOLE_HANDLER_NAME = "chatcore_console"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

logger = logging.getLogger(__name__)


# 日本語: ログレコードを構造化されたJSON形式に変換するためのカスタムログフォーマッタクラス。
# English: Custom log formatter class to structure log records into JSON strings.
class JsonLogFormatter(logging.Formatter):
    RESERVED_KEYS = {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "request_id",
        "request_method",
        "request_path",
        "stack_info",
        "thread",
        "threadName",
    }

    # ログレコードをJSON文字列形式にフォーマットする
    # Format the log record into a JSON-serialized string.
    # 日本語: ログレコードの内容（タイムスタンプ、レベル、メッセージ、リクエストID等）をJSON形式にフォーマットします。
    # English: Format the log record (timestamp, level, message, request ID, etc.) into a JSON-serialized string.
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "request_method": getattr(record, "request_method", "-"),
            "request_path": getattr(record, "request_path", "-"),
        }

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self.RESERVED_KEYS and not key.startswith("_")
        }
        # 日本語: 与えられた条件に基づいて分岐処理を行います。
        # English: Branch execution flow based on the given conditions.
        if extras:
            payload["extra"] = extras

        # 日本語: 与えられた条件に基づいて分岐処理を行います。
        # English: Branch execution flow based on the given conditions.
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False)


# 環境変数から正の整数値を安全に解析し、無効な場合はデフォルト値を返すヘルパー関数
# Safely parse a positive integer from environment variables or fallback to a default value.
# 日本語: 環境変数から正の整数値を安全にパースします。無効な場合はデフォルト値にフォールバックします。
# English: Safely parse a positive integer from environment variables, falling back to a default value if invalid.
def _parse_positive_int_env(env_name: str, default_value: int) -> int:
    raw_value = os.getenv(env_name, str(default_value))
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        parsed_value = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid %s value '%s'. Falling back to %s.",
            env_name,
            raw_value,
            default_value,
        )
        return default_value

    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if parsed_value <= 0:
        logger.warning(
            "Invalid %s value '%s'. Falling back to %s.",
            env_name,
            raw_value,
            default_value,
        )
        return default_value
    return parsed_value


# 指定された名前を持つ既存のログハンドラをルートロガーから削除してクローズする
# Remove and close an existing log handler with the specified name from the root logger.
# 日本語: ルートロガーから指定された名前を持つ既存のログハンドラを削除し、クローズします。
# English: Remove and close an existing log handler with the specified name from the root logger.
def _replace_named_handler(root_logger: logging.Logger, handler_name: str) -> None:
    # 日本語: イテレータから要素を順に取得し、反復処理を行います。
    # English: Iterate over the elements sequentially and perform operations.
    for existing_handler in list(root_logger.handlers):
        if getattr(existing_handler, "name", "") == handler_name:
            root_logger.removeHandler(existing_handler)
            existing_handler.close()


# ログ出力形式の設定（plainかjson）に基づいてフォーマッタを構築する
# Build a log formatter based on the log output format setting (plain or json).
# 日本語: ログ出力設定（"plain" または "json"）に基づいてログフォーマッタオブジェクトを構築します。
# English: Build a log formatter object based on the output configuration ("plain" or "json").
def _build_formatter(log_output: str) -> logging.Formatter:
    # 日本語: 与えられた条件に基づいて分岐処理を行います。
    # English: Branch execution flow based on the given conditions.
    if log_output == "plain":
        return logging.Formatter(LOG_FORMAT)
    return JsonLogFormatter()


# ローテーションログファイル用ハンドラ（RotatingFileHandler）を構築する
# Build a RotatingFileHandler to write logs to a file with size rotation.
# 日本語: サイズ制限および世代管理を指定してファイルローテーション用のハンドラを構築します。
# English: Build a RotatingFileHandler with size rotation and backup configurations.
def _build_rotating_handler(
    *,
    file_path: Path,
    level: int,
    max_bytes: int,
    backup_count: int,
    handler_name: str,
    formatter: logging.Formatter,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        file_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler.addFilter(RequestContextFilter())
    handler.name = handler_name
    return handler


# コンソール（標準出力）用ハンドラ（StreamHandler）を構築する
# Build a StreamHandler to output logs to the console (stdout/stderr).
# 日本語: 標準出力用のコンソールハンドラ（StreamHandler）を構築します。
# English: Build a StreamHandler to output logs to the console.
def _build_console_handler(
    *,
    level: int,
    formatter: logging.Formatter,
) -> logging.StreamHandler:
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler.addFilter(RequestContextFilter())
    handler.name = CONSOLE_HANDLER_NAME
    return handler


# 環境変数等に基づいてアプリケーション全体のロギング設定を適用する
# Apply application-wide logging configuration based on environment variables and defaults.
# 日本語: 環境変数やデフォルト値に基づいて、アプリケーション全体のロギング設定を適用します。
# English: Configure and apply the application-wide logging settings based on environment variables and defaults.
def configure_logging() -> None:
    log_level_name = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    resolved_log_level = getattr(logging, log_level_name, logging.INFO)
    log_output = os.getenv("LOG_OUTPUT", DEFAULT_LOG_OUTPUT).lower()

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_log_level)

    log_dir = Path(os.getenv("LOG_DIR", DEFAULT_LOG_DIR))
    # 日本語: エラー（例外）発生の可能性がある処理を実行し、適切に捕捉します。
    # English: Execute operations that might raise exceptions and handle them appropriately.
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        root_logger.exception("Failed to create log directory: %s", log_dir)
        return

    max_bytes = _parse_positive_int_env("LOG_MAX_BYTES", DEFAULT_LOG_MAX_BYTES)
    backup_count = _parse_positive_int_env("LOG_BACKUP_COUNT", DEFAULT_LOG_BACKUP_COUNT)
    app_log_file = log_dir / os.getenv("APP_LOG_FILE", DEFAULT_APP_LOG_FILE)
    error_log_file = log_dir / os.getenv("ERROR_LOG_FILE", DEFAULT_ERROR_LOG_FILE)
    formatter = _build_formatter(log_output)

    # 日本語: イテレータから要素を順に取得し、反復処理を行います。
    # English: Iterate over the elements sequentially and perform operations.
    for handler_name in (CONSOLE_HANDLER_NAME, APP_LOG_HANDLER_NAME, ERROR_LOG_HANDLER_NAME):
        _replace_named_handler(root_logger, handler_name)

    root_logger.addHandler(
        _build_console_handler(level=resolved_log_level, formatter=formatter)
    )
    root_logger.addHandler(
        _build_rotating_handler(
            file_path=app_log_file,
            level=resolved_log_level,
            max_bytes=max_bytes,
            backup_count=backup_count,
            handler_name=APP_LOG_HANDLER_NAME,
            formatter=formatter,
        )
    )
    root_logger.addHandler(
        _build_rotating_handler(
            file_path=error_log_file,
            level=logging.ERROR,
            max_bytes=max_bytes,
            backup_count=backup_count,
            handler_name=ERROR_LOG_HANDLER_NAME,
            formatter=formatter,
        )
    )
