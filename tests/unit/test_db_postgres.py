import os
import unittest
from unittest.mock import patch

import services.db as db


# 日本語: テスト用の擬似Dummy Connectionクラスです。
# English: Mock Dummy Connection class for testing.
class DummyConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self):
        self.cursor_args = None
        self.cursor_kwargs = None
        self.rollback_called = False
        self.closed = 0

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def cursor(self, *args, **kwargs):
        self.cursor_args = args
        self.cursor_kwargs = kwargs
        return "cursor"

    # 日本語: テスト用の処理の入口関数rollbackです。
# English: Entry point helper function rollback for testing.
    def rollback(self):
        self.rollback_called = True

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def close(self):
        self.closed = 1


# 日本語: テスト用の擬似Dummy Threaded Connection Poolクラスです。
# English: Mock Dummy Threaded Connection Pool class for testing.
class DummyThreadedConnectionPool:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, connection, minconn, maxconn, kwargs):
        self._connection = connection
        self.minconn = minconn
        self.maxconn = maxconn
        self.kwargs = kwargs
        self.getconn_calls = 0
        self.putconn_calls = []
        self.closeall_calls = 0

    # 日本語: テスト用の処理の入口関数getconnです。
# English: Entry point helper function getconn for testing.
    def getconn(self):
        self.getconn_calls += 1
        return self._connection

    # 日本語: テスト用の処理の入口関数putconnです。
# English: Entry point helper function putconn for testing.
    def putconn(self, connection, close=False):
        self.putconn_calls.append((connection, close))

    # 日本語: 後処理を実行します。
# English: Perform cleanup operations.
    def closeall(self):
        self.closeall_calls += 1


# 日本語: テスト用の擬似Dummy Pool Factoryクラスです。
# English: Mock Dummy Pool Factory class for testing.
class DummyPoolFactory:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, connection):
        self._connection = connection
        self.instances = []

    # 日本語: テスト用の処理の入口関数callです。
# English: Entry point helper function call for testing.
    def __call__(self, minconn, maxconn, **kwargs):
        pool = DummyThreadedConnectionPool(self._connection, minconn, maxconn, kwargs)
        self.instances.append(pool)
        return pool


# 日本語: テスト用の擬似Dummy Extrasクラスです。
# English: Mock Dummy Extras class for testing.
class DummyExtras:
    # 日本語: テスト用のReal Dict Cursorクラスです。
# English: Real Dict Cursor class for testing.
    class RealDictCursor:
        pass


# 日本語: D B Configの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of D B Config.
class DBConfigTestCase(unittest.TestCase):
    # 日本語: テスト用の処理の入口関数setUpです。
# English: Entry point helper function setUp for testing.
    def setUp(self):
        db.close_db_pool()

    # 日本語: テスト用の処理の入口関数tearDownです。
# English: Entry point helper function tearDown for testing.
    def tearDown(self):
        db.close_db_pool()

    # 日本語: poolを使用する場合、getDBconnectionusesPostgreSQLenvことを検証します。
    # English: Verify that get db connection uses postgres env with pool.
    def test_get_db_connection_uses_postgres_env_with_pool(self):
        connection = DummyConnection()
        pool_factory = DummyPoolFactory(connection)
        env = {
            "POSTGRES_HOST": "pg-host",
            "POSTGRES_USER": "pg-user",
            "POSTGRES_PASSWORD": "pg-pass",
            "POSTGRES_DB": "pg-db",
            "POSTGRES_PORT": "5555",
            "DB_POOL_MIN_CONN": "2",
            "DB_POOL_MAX_CONN": "8",
        }
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(os.environ, env, clear=True), patch.object(
            db, "ThreadedConnectionPool", pool_factory
        ), patch.object(db, "psycopg2", object()), patch.object(db, "extras", DummyExtras):
            proxy = db.get_db_connection()
            cursor = proxy.cursor(dictionary=True)
            proxy.close()

        self.assertEqual(cursor, "cursor")
        self.assertEqual(len(pool_factory.instances), 1)
        pool = pool_factory.instances[0]
        self.assertEqual(pool.kwargs["host"], "pg-host")
        self.assertEqual(pool.kwargs["user"], "pg-user")
        self.assertEqual(pool.kwargs["password"], "pg-pass")
        self.assertEqual(pool.kwargs["dbname"], "pg-db")
        self.assertEqual(pool.kwargs["port"], 5555)
        self.assertEqual(pool.minconn, 2)
        self.assertEqual(pool.maxconn, 8)
        self.assertEqual(connection.cursor_kwargs["cursor_factory"], DummyExtras.RealDictCursor)
        self.assertTrue(connection.rollback_called)
        self.assertEqual(len(pool.putconn_calls), 2)
        self.assertFalse(pool.putconn_calls[-1][1])

    # 日本語: mysqlenvへ、getDBconnectionfallsことを検証します。
    # English: Verify that get db connection falls back to mysql env.
    def test_get_db_connection_falls_back_to_mysql_env(self):
        connection = DummyConnection()
        pool_factory = DummyPoolFactory(connection)
        env = {
            "MYSQL_HOST": "mysql-host",
            "MYSQL_USER": "mysql-user",
            "MYSQL_PASSWORD": "mysql-pass",
            "MYSQL_DATABASE": "mysql-db",
            "MYSQL_PORT": "15432",
        }
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(os.environ, env, clear=True), patch.object(
            db, "ThreadedConnectionPool", pool_factory
        ), patch.object(db, "psycopg2", object()), patch.object(db, "extras", DummyExtras):
            proxy = db.get_db_connection()
            proxy.close()

        self.assertEqual(len(pool_factory.instances), 1)
        pool = pool_factory.instances[0]
        self.assertEqual(pool.kwargs["host"], "mysql-host")
        self.assertEqual(pool.kwargs["user"], "mysql-user")
        self.assertEqual(pool.kwargs["password"], "mysql-pass")
        self.assertEqual(pool.kwargs["dbname"], "mysql-db")
        self.assertEqual(pool.kwargs["port"], 15432)

    # 日本語: getDBconnectionreusesexistingpoolことを検証します。
    # English: Verify that get db connection reuses existing pool.
    def test_get_db_connection_reuses_existing_pool(self):
        connection = DummyConnection()
        pool_factory = DummyPoolFactory(connection)
        env = {
            "POSTGRES_HOST": "pg-host",
            "POSTGRES_USER": "pg-user",
            "POSTGRES_PASSWORD": "pg-pass",
            "POSTGRES_DB": "pg-db",
            "POSTGRES_PORT": "5432",
        }
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(os.environ, env, clear=True), patch.object(
            db, "ThreadedConnectionPool", pool_factory
        ), patch.object(db, "psycopg2", object()), patch.object(db, "extras", DummyExtras):
            conn1 = db.get_db_connection()
            conn1.close()
            conn2 = db.get_db_connection()
            conn2.close()

        self.assertEqual(len(pool_factory.instances), 1)
        pool = pool_factory.instances[0]
        self.assertEqual(pool.getconn_calls, 3)
        self.assertEqual(len(pool.putconn_calls), 3)

    # 日本語: productionのとき、getDBconnectionusesproductionpoolenvことを検証します。
    # English: Verify that get db connection uses production pool env when production.
    def test_get_db_connection_uses_production_pool_env_when_production(self):
        connection = DummyConnection()
        pool_factory = DummyPoolFactory(connection)
        env = {
            "FASTAPI_ENV": "production",
            "POSTGRES_HOST": "pg-host",
            "POSTGRES_USER": "pg-user",
            "POSTGRES_PASSWORD": "pg-pass",
            "POSTGRES_DB": "pg-db",
            "POSTGRES_PORT": "5432",
            "DB_POOL_MIN_CONN": "1",
            "DB_POOL_MAX_CONN": "10",
            "DB_POOL_MIN_CONN_PRODUCTION": "4",
            "DB_POOL_MAX_CONN_PRODUCTION": "20",
        }
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch.dict(os.environ, env, clear=True), patch.object(
            db, "ThreadedConnectionPool", pool_factory
        ), patch.object(db, "psycopg2", object()), patch.object(db, "extras", DummyExtras):
            proxy = db.get_db_connection()
            proxy.close()

        self.assertEqual(len(pool_factory.instances), 1)
        pool = pool_factory.instances[0]
        self.assertEqual(pool.minconn, 4)
        self.assertEqual(pool.maxconn, 20)


if __name__ == "__main__":
    unittest.main()
