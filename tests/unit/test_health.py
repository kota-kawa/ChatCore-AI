import unittest
from unittest.mock import patch

from services.health import get_liveness_status, get_readiness_status


# 日本語: DummyCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to DummyCursor.
class DummyCursor:
    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query):
        self.query = query

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        return (1,)

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        return None


# 日本語: DummyConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to DummyConnection.
class DummyConnection:
    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self):
        return DummyCursor()

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        return None

    # 日本語: コンテキスト開始時に必要な準備を行います。
    # English: Prepare the object when entering the context.
    def __enter__(self):
        return self

    # 日本語: コンテキスト終了時の後片付けを行います。
    # English: Clean up when leaving the context.
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# 日本語: HealthServiceTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to HealthServiceTestCase.
class HealthServiceTestCase(unittest.TestCase):
    # 日本語: test liveness status is ok のテスト検証を担当します。
    # English: Handle verifying test behavior for test liveness status is ok.
    def test_liveness_status_is_ok(self):
        self.assertEqual(get_liveness_status(), {"status": "ok"})

    # 日本語: test readiness is ok when dependencies are available のテスト検証を担当します。
    # English: Handle verifying test behavior for test readiness is ok when dependencies are available.
    def test_readiness_is_ok_when_dependencies_are_available(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.health.get_db_connection", return_value=DummyConnection()):
            with patch("services.health.is_redis_configured", return_value=True):
                with patch("services.health.get_redis_client", return_value=object()):
                    payload, status_code = get_readiness_status()

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["components"]["database"]["status"], "ok")
        self.assertEqual(payload["components"]["redis"]["status"], "ok")

    # 日本語: test readiness is degraded when optional redis is unavailable のテスト検証を担当します。
    # English: Handle verifying test behavior for test readiness is degraded when optional redis is unavailable.
    def test_readiness_is_degraded_when_optional_redis_is_unavailable(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.health.get_db_connection", return_value=DummyConnection()):
            with patch("services.health.is_redis_configured", return_value=True):
                with patch("services.health.get_redis_client", return_value=None):
                    payload, status_code = get_readiness_status()

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["components"]["redis"]["status"], "degraded")

    # 日本語: test readiness is error when database is unavailable のテスト検証を担当します。
    # English: Handle verifying test behavior for test readiness is error when database is unavailable.
    def test_readiness_is_error_when_database_is_unavailable(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("services.health.get_db_connection", side_effect=RuntimeError("db down")):
            with patch("services.health.is_redis_configured", return_value=False):
                payload, status_code = get_readiness_status()

        self.assertEqual(status_code, 503)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["components"]["database"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
