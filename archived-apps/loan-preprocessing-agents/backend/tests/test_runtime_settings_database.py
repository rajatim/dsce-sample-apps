"""Run only against an explicitly selected disposable PostgreSQL database."""
import os
from pathlib import Path
import unittest
import psycopg
from psycopg import sql

DSN = os.getenv('RUNTIME_TEST_ADMIN_DSN')
SCHEMA = Path(__file__).parents[1] / 'migrations' / 'runtime_config_v1.sql'

@unittest.skipUnless(DSN, 'explicit disposable database required')
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = psycopg.connect(DSN, autocommit=True)
        database = cls.admin.execute('select current_database()').fetchone()[0]
        if database != 'runtime_settings_test_20261003':
            raise RuntimeError('Refusing non-test database')
        marker = cls.admin.execute("select shobj_description(oid,'pg_database') from pg_database where datname=current_database()").fetchone()[0]
        if marker != 'Owned by Codex runtime-config-20261003; isolated settings verification only':
            raise RuntimeError('Test database ownership marker missing')
        cls.admin.execute('drop schema if exists runtime_config cascade')

    @classmethod
    def tearDownClass(cls):
        cls.admin.close()

    def test_roles_and_atomic_revision_constraints(self):
        self.assertTrue(SCHEMA.exists(), 'versioned schema exists')
        self.admin.execute('grant create on database runtime_settings_test_20261003 to runtime_test_owner')
        import importlib.util
        from unittest.mock import patch
        from sqlalchemy import create_engine
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        path = SCHEMA.parent / 'versions/0002_runtime_settings.py'
        spec = importlib.util.spec_from_file_location('runtime_migration', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine(DSN.replace('postgresql:', 'postgresql+psycopg:',1))
        try:
            with engine.begin() as connection, patch.dict(os.environ, {'CONFIG_SCHEMA_OWNER':'runtime_test_owner'}):
                with Operations.context(MigrationContext.configure(connection)):
                    migration.upgrade()
        finally:
            engine.dispose()
        with self.admin.transaction():
            self.admin.execute("insert into runtime_config.principals(role_name,environment,application,can_write) values ('runtime_test_dsce','test','dsce',false),('runtime_test_loan','test','loan',false),('runtime_test_writer','test','dsce',true),('runtime_test_writer','test','loan',true) on conflict do nothing")
            for role in ('runtime_test_dsce', 'runtime_test_loan', 'runtime_test_writer'):
                self.admin.execute(sql.SQL('grant usage on schema runtime_config to {}').format(sql.Identifier(role)))
                self.admin.execute(sql.SQL('grant select on runtime_config.principals,runtime_config.revisions,runtime_config.active,runtime_config.audit to {}').format(sql.Identifier(role)))
            self.admin.execute('grant insert on runtime_config.revisions to runtime_test_writer')
            self.admin.execute('grant insert,update on runtime_config.active to runtime_test_writer')
        # Actual authenticated sessions, not a caller-controlled app variable.
        connection = dict(self.admin.info.get_parameters())
        connection.pop('user', None)
        with psycopg.connect(**connection, user='runtime_test_writer') as writer:
            for app in ('dsce', 'loan'):
                writer.execute("insert into runtime_config.revisions(environment,application,group_name,revision,schema_version,key_id,nonce,ciphertext) values ('test',%s,'auth',%s,1,'test-key',%s,%s)", (app, '00000000-0000-4000-8000-000000000001', b'012345678901', b'encrypted-only-tag'))
                writer.execute("insert into runtime_config.active(environment,application,group_name,revision) values ('test',%s,'auth','00000000-0000-4000-8000-000000000001')", (app,))
        for role, app in [('runtime_test_dsce', 'dsce'), ('runtime_test_loan', 'loan')]:
            with psycopg.connect(**connection, user=role, autocommit=True) as reader:
                self.assertEqual(reader.execute('select application from runtime_config.revisions').fetchall(), [(app,)])
                self.assertEqual(reader.execute('select application from runtime_config.active').fetchall(), [(app,)])
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    reader.execute("update runtime_config.active set revision=revision")
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    reader.execute('create table runtime_config.unauthorized(id int)')
        with psycopg.connect(**connection, user='runtime_test_writer', autocommit=True) as writer:
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                writer.execute("insert into runtime_config.active(environment,application,group_name,revision) values ('test','loan','other','00000000-0000-4000-8000-000000000001')")
            with self.assertRaises(psycopg.errors.UniqueViolation):
                writer.execute("insert into runtime_config.revisions(environment,application,group_name,revision,schema_version,key_id,nonce,ciphertext) values ('test','loan','other','00000000-0000-4000-8000-000000000002',1,'test-key',%s,%s)", (b'012345678901', b'encrypted-only-tag'))
        self.assertEqual(self.admin.execute('select count(*) from runtime_config.audit').fetchone()[0], 2)

if __name__ == '__main__':
    unittest.main()
