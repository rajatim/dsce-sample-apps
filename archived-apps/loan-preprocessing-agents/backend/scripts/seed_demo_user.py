import argparse
from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path
import sys


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))

from sqlalchemy.orm import Session, sessionmaker

from database import build_engine
import models
import security


class DemoUserConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class DemoUserSettings:
    username: str
    password: str
    first_name: str
    last_name: str
    date_of_birth: date

    @classmethod
    def from_environment(cls) -> "DemoUserSettings":
        variable_names = (
            "DEMO_USERNAME",
            "DEMO_PASSWORD",
            "DEMO_FIRST_NAME",
            "DEMO_LAST_NAME",
            "DEMO_DATE_OF_BIRTH",
        )
        values = {}
        for variable_name in variable_names:
            value = os.getenv(variable_name)
            if not value:
                raise DemoUserConfigurationError(
                    f"Missing required environment variable: {variable_name}"
                )
            values[variable_name] = value

        try:
            date_of_birth = date.fromisoformat(values["DEMO_DATE_OF_BIRTH"])
        except ValueError as error:
            raise DemoUserConfigurationError(
                "DEMO_DATE_OF_BIRTH must use ISO YYYY-MM-DD format"
            ) from error

        return cls(
            username=values["DEMO_USERNAME"],
            password=values["DEMO_PASSWORD"],
            first_name=values["DEMO_FIRST_NAME"],
            last_name=values["DEMO_LAST_NAME"],
            date_of_birth=date_of_birth,
        )


@dataclass(frozen=True)
class DemoUserSeedResult:
    created: bool
    password_rotated: bool = False


def seed_demo_user(
    session: Session,
    settings: DemoUserSettings,
    rotate_password: bool = False,
) -> DemoUserSeedResult:
    existing_user = (
        session.query(models.User)
        .filter(models.User.username == settings.username)
        .one_or_none()
    )
    if existing_user is not None:
        if rotate_password:
            existing_user.hashed_password = security.get_password_hash(
                settings.password
            )
            session.commit()
            return DemoUserSeedResult(created=False, password_rotated=True)
        return DemoUserSeedResult(created=False)

    session.add(
        models.User(
            username=settings.username,
            hashed_password=security.get_password_hash(settings.password),
            first_name=settings.first_name,
            last_name=settings.last_name,
            date_of_birth=settings.date_of_birth,
        )
    )
    session.commit()
    return DemoUserSeedResult(created=True)


def _database_url_from_environment() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise DemoUserConfigurationError(
            "Missing required environment variable: DATABASE_URL"
        )
    return database_url


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Seed the configured demo user")
    parser.add_argument("--rotate-password", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    engine = None
    session = None
    try:
        args = _parse_args(argv)
        settings = DemoUserSettings.from_environment()
        engine = build_engine(_database_url_from_environment())
        session = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
        )()
        result = seed_demo_user(
            session,
            settings,
            rotate_password=args.rotate_password,
        )
        print(f"created={str(result.created).lower()}")
        print(f"password_rotated={str(result.password_rotated).lower()}")
        return 0
    except DemoUserConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Demo user seed failed", file=sys.stderr)
        return 1
    finally:
        if session is not None:
            session.close()
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
