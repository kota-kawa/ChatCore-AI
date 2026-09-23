# 日本語: テストパッケージ全体のエントリーポイントです。
"""Test package."""


from services.usage_metering import set_usage_sink

# 単体テストは DB に接続しないため、API 使用量の記録は捨てる。記録そのものを
# 確かめるテストは自前の記録先に差し替える。
# Unit tests run without a database, so API usage records are discarded. Tests that check
# the records install their own sink.
set_usage_sink(lambda _increment: None)
