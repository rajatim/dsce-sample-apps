import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from database import Base
from models import User
from security import verify_password
from scripts.seed_demo_user import DemoUserSettings, seed_demo_user


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
CLI_PATH = BACKEND_DIRECTORY / "scripts" / "seed_demo_user.py"


class DemoUserSeedTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.settings = DemoUserSettings(
            username="tom_miller",
            password="Pass1234",
            first_name="Tom",
            last_name="Miller",
            date_of_birth=date(1980, 1, 21),
        )

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_seed_creates_user_once_and_never_logs_password(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            first = seed_demo_user(self.session, self.settings)
            second = seed_demo_user(self.session, self.settings)

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(self.session.query(User).count(), 1)
        self.assertNotIn(self.settings.password, output.getvalue())

    def test_seed_rotates_an_existing_password_only_when_explicitly_requested(self):
        seed_demo_user(self.session, self.settings)
        user = self.session.query(User).filter_by(username="tom_miller").one()
        original_hash = user.hashed_password
        rotated_settings = DemoUserSettings(
            username="tom_miller",
            password="NewPass5678",
            first_name="Changed",
            last_name="Profile",
            date_of_birth=date(2000, 2, 2),
        )

        unchanged = seed_demo_user(self.session, rotated_settings)
        self.session.refresh(user)

        self.assertFalse(unchanged.created)
        self.assertFalse(unchanged.password_rotated)
        self.assertEqual(user.hashed_password, original_hash)
        self.assertEqual(user.first_name, "Tom")
        self.assertEqual(user.last_name, "Miller")
        self.assertEqual(user.date_of_birth, date(1980, 1, 21))

        rotated = seed_demo_user(
            self.session,
            rotated_settings,
            rotate_password=True,
        )
        self.session.refresh(user)

        self.assertFalse(rotated.created)
        self.assertTrue(rotated.password_rotated)
        self.assertNotEqual(user.hashed_password, original_hash)
        self.assertTrue(verify_password("NewPass5678", user.hashed_password))
        self.assertEqual(user.first_name, "Tom")
        self.assertEqual(user.last_name, "Miller")
        self.assertEqual(user.date_of_birth, date(1980, 1, 21))

    def test_settings_fail_closed_when_any_required_demo_variable_is_missing(self):
        environment = {
            "DEMO_USERNAME": "tom_miller",
            "DEMO_PASSWORD": "Pass1234",
            "DEMO_FIRST_NAME": "Tom",
            "DEMO_LAST_NAME": "Miller",
            "DEMO_DATE_OF_BIRTH": "1980-01-21",
        }
        self.assertTrue(hasattr(DemoUserSettings, "from_environment"))

        with patch.dict(os.environ, environment, clear=True):
            loaded = DemoUserSettings.from_environment()

        self.assertEqual(loaded, self.settings)

        for missing_name in environment:
            incomplete = environment.copy()
            incomplete.pop(missing_name)
            with self.subTest(missing_name=missing_name):
                with patch.dict(os.environ, incomplete, clear=True):
                    with self.assertRaisesRegex(ValueError, missing_name):
                        DemoUserSettings.from_environment()

    def test_settings_reject_an_invalid_date_without_echoing_values(self):
        environment = {
            "DEMO_USERNAME": "tom_miller",
            "DEMO_PASSWORD": "do-not-echo-this",
            "DEMO_FIRST_NAME": "Tom",
            "DEMO_LAST_NAME": "Miller",
            "DEMO_DATE_OF_BIRTH": "not-a-date",
        }

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(ValueError) as raised:
                DemoUserSettings.from_environment()

        message = str(raised.exception)
        self.assertIn("DEMO_DATE_OF_BIRTH", message)
        for value in environment.values():
            self.assertNotIn(value, message)


class DemoUserSeedCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "seed.db"
        self.database_url = f"sqlite:///{self.database_path}"
        self.engine = create_engine(self.database_url)
        Base.metadata.create_all(self.engine)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "DEMO_USERNAME": "cli_demo_user",
                "DEMO_PASSWORD": "cli-secret-password",
                "DEMO_FIRST_NAME": "CLI",
                "DEMO_LAST_NAME": "Demo",
                "DEMO_DATE_OF_BIRTH": "1990-03-04",
            }
        )

    def tearDown(self):
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def _run_cli(self, environment, *arguments):
        return subprocess.run(
            [sys.executable, str(CLI_PATH), *arguments],
            cwd=BACKEND_DIRECTORY,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_cli_requires_database_url_and_does_not_echo_password(self):
        environment = self.environment.copy()
        environment.pop("DATABASE_URL", None)

        result = self._run_cli(environment)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL", result.stderr)
        self.assertNotIn(environment["DEMO_PASSWORD"], result.stdout)
        self.assertNotIn(environment["DEMO_PASSWORD"], result.stderr)

    def test_cli_seeds_the_configured_database_idempotently(self):
        environment = self.environment | {"DATABASE_URL": self.database_url}

        first = self._run_cli(environment)
        with sessionmaker(bind=self.engine)() as session:
            first_user = session.query(User).filter_by(username="cli_demo_user").one()
            first_hash = first_user.hashed_password
        second = self._run_cli(environment)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        with sessionmaker(bind=self.engine)() as session:
            users = session.query(User).all()
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0].hashed_password, first_hash)
            self.assertEqual(users[0].first_name, "CLI")
            self.assertEqual(users[0].last_name, "Demo")
            self.assertEqual(users[0].date_of_birth, date(1990, 3, 4))
        for output in (first.stdout, first.stderr, second.stdout, second.stderr):
            self.assertNotIn(environment["DEMO_PASSWORD"], output)

    def test_cli_rotates_password_only_with_the_explicit_flag(self):
        environment = self.environment | {"DATABASE_URL": self.database_url}
        first = self._run_cli(environment)
        self.assertEqual(first.returncode, 0, first.stderr)
        with sessionmaker(bind=self.engine)() as session:
            original_hash = session.query(User).one().hashed_password

        rotated_environment = environment | {
            "DEMO_PASSWORD": "explicitly-rotated-password"
        }
        rotated = self._run_cli(rotated_environment, "--rotate-password")

        self.assertEqual(rotated.returncode, 0, rotated.stderr)
        with sessionmaker(bind=self.engine)() as session:
            user = session.query(User).one()
            self.assertNotEqual(user.hashed_password, original_hash)
            self.assertTrue(
                verify_password(
                    rotated_environment["DEMO_PASSWORD"],
                    user.hashed_password,
                )
            )
        self.assertNotIn(rotated_environment["DEMO_PASSWORD"], rotated.stdout)
        self.assertNotIn(rotated_environment["DEMO_PASSWORD"], rotated.stderr)


if __name__ == "__main__":
    unittest.main()
