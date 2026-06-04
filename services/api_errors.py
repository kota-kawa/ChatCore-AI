from __future__ import annotations

import re
from typing import Any

DEFAULT_RETRY_AFTER_SECONDS = 60
_RETRY_AFTER_SECONDS_PATTERN = re.compile(r"(?P<seconds>\d+)秒")


class ApiServiceError(Exception):
    # APIエラーを表すカスタム例外クラスの初期化
    # Initialize the custom exception class representing API errors.
    def __init__(
        self,
        message: str,
        status_code: int,
        *,
        status: str | None = None,
        error_key: str = "error",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = int(status_code)
        self.status = status
        self.error_key = error_key
        self.headers = dict(headers or {})

    # 例外オブジェクトをクライアントへのJSONレスポンス用の辞書に変換する
    # Convert the exception object to a dictionary for JSON response to the client.
    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {self.error_key: self.message}
        if self.status is not None:
            payload["status"] = self.status
        return payload


class ResourceNotFoundError(ApiServiceError):
    # リソースが見つからない場合（404）のエラー例外の初期化
    # Initialize the error exception for resource not found (404) scenarios.
    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message, 404, status=status)


class ForbiddenOperationError(ApiServiceError):
    # 操作が禁止されている場合（403）のエラー例外の初期化
    # Initialize the error exception for forbidden operations (403).
    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message, 403, status=status)


# エラーメッセージ文字列から「〇〇秒」の部分を抽出し、再試行待ち秒数（整数）を解析する
# Parse the retry-after duration (in seconds) from an error message containing a seconds pattern.
def parse_retry_after_seconds(
    message: str | None,
    *,
    default: int | None = None,
) -> int | None:
    if isinstance(message, str):
        matched = _RETRY_AFTER_SECONDS_PATTERN.search(message)
        if matched is not None:
            try:
                return max(int(matched.group("seconds")), 1)
            except (TypeError, ValueError):
                return default
    if default is None:
        return None
    return max(int(default), 1)
