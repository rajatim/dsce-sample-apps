"""Add encrypted, role-scoped runtime configuration without changing business tables.

Revision ID: 0002
Revises: 0001
"""
import os
from pathlib import Path
import re
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != 'postgresql':
        # SQLite remains a legacy development store, not a settings backend.
        return
    owner = os.environ.get('CONFIG_SCHEMA_OWNER', '')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', owner):
        raise RuntimeError('CONFIG_SCHEMA_OWNER must identify the provisioned migration role')
    role = connection.execute(sa.text('SELECT rolsuper,rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname=:owner'), {'owner':owner}).first()
    if role is None or any(role):
        raise RuntimeError('Settings owner must be a non-login, non-superuser role without BYPASSRLS')
    quoted = connection.dialect.identifier_preparer.quote(owner)
    connection.exec_driver_sql(f'SET LOCAL ROLE {quoted}')
    connection.exec_driver_sql((Path(__file__).parents[1] / 'runtime_config_v1.sql').read_text())
    connection.exec_driver_sql('RESET ROLE')


def downgrade():
    raise RuntimeError('Runtime configuration history is retained; use application rollback, not schema deletion')
