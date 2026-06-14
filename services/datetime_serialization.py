from __future__ import annotations

from datetime import datetime


# 日本語: serialize datetime iso のシリアライズ処理を担当します。
# English: Handle serializing for serialize datetime iso.
def serialize_datetime_iso(value: datetime | None) -> str | None:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if value is None:
        return None
    return value.isoformat()
