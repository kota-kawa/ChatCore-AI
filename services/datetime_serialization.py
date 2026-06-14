from __future__ import annotations

from datetime import datetime


# 日時オブジェクトを ISO 8601 形式の文字列にシリアライズする
# Serialize a datetime object to an ISO 8601 formatted string
def serialize_datetime_iso(value: datetime | None) -> str | None:
    # 値が None の場合は None を返す
    # Return None if the input value is None
    if value is None:
        return None
    return value.isoformat()
