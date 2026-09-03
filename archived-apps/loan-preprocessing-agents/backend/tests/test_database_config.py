import os
import unittest
from unittest.mock import patch

from database import build_engine, resolve_database_url


class DatabaseConfigTests(unittest.TestCase):
    def test_sqlite_uses_check_same_thread_false(self):
        engine = build_engine("sqlite:///./test.db")

        self.assertEqual(engine.url.get_backend_name(), "sqlite")

    def test_postgresql_uses_psycopg_and_pool_pre_ping(self):
        engine = build_engine(
            "postgresql+psycopg://loan_app_dev:secret@127.0.0.1:5432/loan_poc_dev"
        )

        self.assertEqual(engine.url.drivername, "postgresql+psycopg")
        self.assertTrue(engine.pool._pre_ping)

    def test_missing_database_url_keeps_sqlite_rollback_path(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_database_url(), "sqlite:///./loan_app.db")


if __name__ == "__main__":
    unittest.main()
