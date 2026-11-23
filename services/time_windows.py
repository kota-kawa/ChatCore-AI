"""日次クォータやレート制限の期限を「次の 0 時」に合わせるための時刻計算。

Time calculations that align quota and rate-limit expiry with the next local midnight.
"""

from __future__ import annotations

from datetime import datetime, timedelta


# 現在時刻から翌日の深夜0時までの残り時間を秒単位で返す(最小1秒)。
# Return the remaining seconds from now until midnight of the next day (at least 1).
def get_seconds_until_tomorrow() -> int:
    now = datetime.now()
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    seconds = int((tomorrow - now).total_seconds())
    return max(seconds, 1)
