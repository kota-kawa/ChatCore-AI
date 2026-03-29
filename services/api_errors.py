from __future__ import annotations

import re
from typing import Any

DEFAULT_RETRY_AFTER_SECONDS = 60
_RETRY_AFTER_SECONDS_PATTERN = re.compile(r"(?P<seconds>\d+)秒")


class ApiServiceError(Exception):
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

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {self.error_key: self.message}
        if self.status is not None:
            payload["status"] = self.status
        return payload


class ResourceNotFoundError(ApiServiceError):
    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message, 404, status=status)


class ForbiddenOperationError(ApiServiceError):
    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message, 403, status=status)


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
