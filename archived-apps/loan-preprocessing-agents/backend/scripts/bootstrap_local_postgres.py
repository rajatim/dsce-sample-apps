"""Create the local PostgreSQL role and database used by the loan POC.

All credentials are supplied through the process environment.  This script
intentionally emits no connection details or passwords.
"""

from dataclasses import dataclass
import os
import re
from collections.abc import Callable, Mapping

import psycopg
from psycopg import sql


IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
DEFAULT_ADMIN_DSN = "postgresql:///postgres"


@dataclass(frozen=True)
class BootstrapConfiguration:
    admin_dsn: str
    database_name: str
    database_user: str
    database_password: str


def validate_name(name: str, environment_name: str) -> str:
    """Return a safe PostgreSQL identifier or reject the environment value."""
    if not IDENTIFIER_PATTERN.fullmatch(name):
        raise ValueError(
            f"{environment_name} must match {IDENTIFIER_PATTERN.pattern}"
        )
    return name


def configuration_from_environment(
    environment: Mapping[str, str] = os.environ,
) -> BootstrapConfiguration:
    """Load bootstrap settings while keeping the password environment-only."""
    password = environment.get("LOAN_DB_PASSWORD")
    if not password:
        raise RuntimeError("LOAN_DB_PASSWORD must be set")

    return BootstrapConfiguration(
        admin_dsn=environment.get("PG_ADMIN_DSN", DEFAULT_ADMIN_DSN),
        database_name=validate_name(
            environment.get("LOAN_DB_NAME", "loan_poc_dev"), "LOAN_DB_NAME"
        ),
        database_user=validate_name(
            environment.get("LOAN_DB_USER", "loan_app_dev"), "LOAN_DB_USER"
        ),
        database_password=password,
    )


def _role_exists(cursor, database_user: str) -> bool:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (database_user,))
    return cursor.fetchone() is not None


def _database_exists(cursor, database_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
    )
    return cursor.fetchone() is not None


def bootstrap(
    configuration: BootstrapConfiguration,
    connect: Callable = psycopg.connect,
) -> None:
    """Create or reconcile the POC role and database without logging secrets."""
    with connect(configuration.admin_dsn) as role_connection:
        with role_connection.cursor() as cursor:
            if not _role_exists(cursor, configuration.database_user):
                cursor.execute(
                    sql.SQL("CREATE ROLE {} LOGIN").format(
                        sql.Identifier(configuration.database_user)
                    )
                )
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(configuration.database_user),
                    # ALTER ROLE is a PostgreSQL utility statement, which does
                    # not support server-side bind parameters.  sql.Literal
                    # delegates escaping to psycopg without exposing the value.
                    sql.Literal(configuration.database_password),
                )
            )

    # PostgreSQL prohibits CREATE DATABASE inside a transaction block.
    with connect(configuration.admin_dsn, autocommit=True) as database_connection:
        with database_connection.cursor() as cursor:
            if not _database_exists(cursor, configuration.database_name):
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(configuration.database_name),
                        sql.Identifier(configuration.database_user),
                    )
                )
            cursor.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(configuration.database_name),
                    sql.Identifier(configuration.database_user),
                )
            )


def main() -> int:
    try:
        bootstrap(configuration_from_environment())
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    except Exception as error:
        raise SystemExit("PostgreSQL bootstrap failed") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
