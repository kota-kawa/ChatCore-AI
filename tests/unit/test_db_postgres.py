import os
import unittest
from unittest.mock import patch

import services.db as db


class DummyConnection:
    def __init__(self):
        self.cursor_args = None
        self.cursor_kwargs = None
        self.rollback_called = False
        self.closed = 0

    def cursor(self, *args, **kwargs):
        self.cursor_args = args
        self.cursor_kwargs = kwargs
        return "cursor"

    def rollback(self):
        self.rollback_called = True

    def close(self):
        self.closed = 1


class DummyThreadedConnectionPool:
    def __init__(self, connection, minconn, maxconn, kwargs):
        self._connection = connection
        self.minconn = minconn
        self.maxconn = maxconn
        self.kwargs = kwargs
        self.getconn_calls = 0
        self.putconn_calls = []
        self.closeall_calls = 0

    def getconn(self):
        self.getconn_calls += 1
        return self._connection

    def putconn(self, connection, close=False):
        self.putconn_calls.append((connection, close))

    def closeall(self):
        self.closeall_calls += 1


class DummyPoolFactory:
    def __init__(self, connection):
        self._connection = connection
        self.instances = []

    def __call__(self, minconn, maxconn, **kwargs):
        pool = DummyThreadedConnectionPool(self._connection, minconn, maxconn, kwargs)
        self.instances.append(pool)
        return pool


class DummyExtras:
    class RealDictCursor:
        pass


class DBConfigTestCase(unittest.TestCase):
    def setUp(self):
        db.close_db_pool()

    def tearDown(self):
        db.close_db_pool()

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
