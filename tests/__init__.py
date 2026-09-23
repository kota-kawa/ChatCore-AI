# 日本語: テストパッケージ全体のエントリーポイントです。
"""Test package."""


from services.repositories.usage_repository import SubjectUsageTotals
from services.usage_limits import UsageTotals, set_usage_totals_reader
from services.usage_metering import set_usage_sink

# 単体テストは DB に接続しないため、API 使用量の記録は捨てる。記録そのものを
# 確かめるテストは自前の記録先に差し替える。
# Unit tests run without a database, so API usage records are discarded. Tests that check
# the records install their own sink.
set_usage_sink(lambda _increment: None)


async def _no_usage(_subject_key, _periods):
    return UsageTotals(
        subject=SubjectUsageTotals(daily_nano_usd=0, weekly_nano_usd=0),
        monthly_total_nano_usd=0,
    )


# 利用上限の判定も DB を読まず、使用量ゼロとして扱う。
# Usage-limit checks likewise read no database and see zero usage.
set_usage_totals_reader(_no_usage)
