import unittest
from unittest.mock import patch

from services.health import get_liveness_status, get_readiness_status


class DummyCursor:
    """
    テスト用のダミーDBカーソルクラス。
    Dummy database cursor class for testing.
    """

    def execute(self, query):
        """
        SQLの実行をシミュレートします。
        Simulate SQL query execution.
        """
        self.query = query

    def fetchone(self):
        """
        モックの取得結果を返します。
        Return a mocked query result.
        """
        return (1,)

    def close(self):
        """
        カーソルを閉じます。
        Close the cursor.
        """
        return None


class DummyConnection:
    """
    テスト用のダミーDBコネクションクラス。
    Dummy database connection class for testing.
    """

    def cursor(self):
        """
        ダミーカーソルを返却します。
        Return the dummy cursor.
        """
        return DummyCursor()

    def close(self):
        """
        コネクションを閉じます。
        Close the connection.
        """
        return None

    def __enter__(self):
        """
        コンテキストに入る時の初期化処理を行います。
        Prepare the object when entering the context.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """
        コンテキストを抜ける時のクリーンアップ処理を行います。
        Clean up when leaving the context.
        """
        self.close()
        return False


class HealthServiceTestCase(unittest.TestCase):
    """
    アプリケーションのヘルスチェック（Liveness/Readiness）機能をテストするクラス。
    Test class to check the liveness and readiness status of the application.
    """

    def test_liveness_status_is_ok(self):
        """
        アプリケーションが起動しているかを示すLiveness状態が常にOKを返すことを検証します。
        Verify that the liveness status of the application always returns OK.
        """
        self.assertEqual(get_liveness_status(), {"status": "ok"})

    def test_readiness_is_ok_when_dependencies_are_available(self):
        """
        依存しているデータベースやRedisが利用可能なとき、Readiness状態がOK(200)を返すことを検証します。
        Verify that readiness returns OK (200) when dependencies (DB and Redis) are available.
        """
        # DB接続とRedis接続を正常状態としてモック
        # Mock DB connection and Redis connection as available
        with patch("services.health.get_db_connection", return_value=DummyConnection()):
            with patch("services.health.is_redis_configured", return_value=True):
                with patch("services.health.get_redis_client", return_value=object()):
                    payload, status_code = get_readiness_status()

        # レスポンスおよび各コンポーネントのステータス検証
        # Assert the response and component statuses
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["components"]["database"]["status"], "ok")
        self.assertEqual(payload["components"]["redis"]["status"], "ok")

    def test_readiness_is_degraded_when_optional_redis_is_unavailable(self):
        """
        必須ではないRedisが利用不可なとき、全体のReadinessはdegraded(200)を返すことを検証します。
        Verify that readiness is degraded (but returns 200) when the optional Redis dependency is unavailable.
        """
        # DBは正常だが、Redisが未稼働の状況をモック
        # Mock where DB is fine but Redis is not running
        with patch("services.health.get_db_connection", return_value=DummyConnection()):
            with patch("services.health.is_redis_configured", return_value=True):
                with patch("services.health.get_redis_client", return_value=None):
                    payload, status_code = get_readiness_status()

        # レスポンスがdegradedであることを検証
        # Assert the response is degraded
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["components"]["redis"]["status"], "degraded")

    def test_readiness_is_error_when_database_is_unavailable(self):
        """
        必須であるデータベースが利用不可なとき、Readinessがerror(503)を返すことを検証します。
        Verify that readiness returns error (503) when the critical database dependency is unavailable.
        """
        # DB接続エラーが発生する状況をモック
        # Mock DB connection raising an error
        with patch("services.health.get_db_connection", side_effect=RuntimeError("db down")):
            with patch("services.health.is_redis_configured", return_value=False):
                payload, status_code = get_readiness_status()

        # レスポンスがerrorであることを検証
        # Assert the response is error
        self.assertEqual(status_code, 503)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["components"]["database"]["status"], "error")


if __name__ == "__main__":
    # テストを実行します
    # Execute the tests
    unittest.main()
