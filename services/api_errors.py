from __future__ import annotations

import re
from typing import Any

DEFAULT_RETRY_AFTER_SECONDS = 60
# エラーメッセージから待機秒数を抽出するための正規表現パターン
# Regular expression pattern to extract waiting seconds from error messages
_RETRY_AFTER_SECONDS_PATTERN = re.compile(r"(?P<seconds>\d+)秒")


# API サービスエラーを表す基本例外クラス
# Base exception class representing API service errors
class ApiServiceError(Exception):
    # APIエラーを表すカスタム例外クラスの初期化
    # Initialize the custom exception class representing API errors
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
    # Convert the exception object to a dictionary for JSON response to the client
    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {self.error_key: self.message}
        # ステータス情報が設定されている場合は、ペイロードに追加する
        # If status information is set, add it to the payload
        if self.status is not None:
            payload["status"] = self.status
        return payload


# リソースが見つからない場合（404）のエラー例外クラス
# Exception class for resource not found errors (404)
class ResourceNotFoundError(ApiServiceError):
    # リソースが見つからないエラー例外の初期化
    # Initialize the resource not found error exception
    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message, 404, status=status)


# 操作が禁止されている場合（403）のエラー例外クラス
# Exception class for forbidden operation errors (403)
class ForbiddenOperationError(ApiServiceError):
    # 禁止操作エラー例外の初期化
    # Initialize the forbidden operation error exception
    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message, 403, status=status)


# エラーメッセージ文字列から「〇〇秒」の部分を抽出し、再試行待ち秒数（整数）を解析する
# Parse the retry-after duration (in seconds) from an error message containing a seconds pattern
def parse_retry_after_seconds(
    message: str | None,
    *,
    default: int | None = None,
) -> int | None:
    # メッセージ文字列が存在する場合、秒数の正規表現パターンを検索する
    # If the message string is present, search for the pattern of seconds
    if isinstance(message, str):
        matched = _RETRY_AFTER_SECONDS_PATTERN.search(message)
        if matched is not None:
            try:
                # 抽出した秒数を整数値に変換し、最低1秒以上にして返す
                # Convert the extracted seconds to an integer and return at least 1 second
                return max(int(matched.group("seconds")), 1)
            except (TypeError, ValueError):
                return default
    # メッセージから解析できなかった場合、デフォルト値があればそれを返す
    # If parsing failed and a default value exists, return it
    if default is None:
        return None
    return max(int(default), 1)
