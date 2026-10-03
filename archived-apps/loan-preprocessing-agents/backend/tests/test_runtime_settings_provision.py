import base64
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import psycopg
from sqlalchemy import create_engine
from alembic.migration import MigrationContext
from alembic.operations import Operations
from scripts.provision_runtime_settings import provision, ROLES
from psycopg import sql
from scripts.runtime_settings import run, read_protected_json

@unittest.skipUnless(os.environ.get('RUNTIME_PROVISION_TEST_DSN'),'explicit disposable provisioning DB required')
class ProvisionTests(unittest.TestCase):
    def test_provision_import_readback_repeat_and_rollback(self):
        dsn=os.environ['RUNTIME_PROVISION_TEST_DSN']
        with psycopg.connect(dsn) as connection:
            self.assertEqual(connection.execute('select current_database()').fetchone()[0],'runtime_settings_provision_20261003')
            for role in ROLES.values():
                marker=connection.execute("select shobj_description(oid,'pg_authid') from pg_roles where rolname=%s",(role,)).fetchone()
                if marker:
                    self.assertEqual(marker[0],'runtime-config:provision-test:runtime_settings_provision_20261003')
                    connection.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                    connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            connection.execute('CREATE TABLE IF NOT EXISTS public.applications(status text)')
        with tempfile.TemporaryDirectory() as directory:
            profile={'environment':'provision-test','database':'runtime_settings_provision_20261003','admin_dsn':dsn,'runtime_url':'postgresql://tim@localhost/runtime_settings_provision_20261003','allowed_hosts':{'dsce':['app.example.test'],'loan':['provider.example.test']}}
            provision(profile,directory,'roles')
            with tempfile.TemporaryDirectory() as missing_primary:
                with self.assertRaisesRegex(RuntimeError,'Primary role credentials missing'):
                    provision(profile,missing_primary,'roles')
            before=read_protected_json(Path(directory)/'dsce-operator.json')
            provision(profile,directory,'roles')
            self.assertEqual(read_protected_json(Path(directory)/'dsce-operator.json'),before)
            path=Path(__file__).parents[1]/'migrations/versions/0002_runtime_settings.py'
            spec=importlib.util.spec_from_file_location('migration',path);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
            engine=create_engine(dsn.replace('postgresql:','postgresql+psycopg:',1))
            with engine.begin() as connection, patch.dict(os.environ,{'CONFIG_SCHEMA_OWNER':'dsce_loan_cfg_owner'}):
                with Operations.context(MigrationContext.configure(connection)): migration.upgrade()
            engine.dispose()
            provision(profile,directory,'grants')
            input_path=Path(directory)/'input.json'
            input_path.write_text(json.dumps({'expected':{},'values':{'AUTH_PROVIDER':'none','NEXTAUTH_SECRET':'synthetic-session-key-32-characters','NEXTAUTH_URL':'https://app.example.test/dsce/api/auth','WIZARD_DATA_SOURCE':'local'}}));input_path.chmod(0o600)
            args=SimpleNamespace(profile=str(Path(directory)/'dsce-operator.json'),environment='provision-test',application='dsce',action='import',input=str(input_path),schema_only=False,dry_run=False)
            result=run(args);self.assertTrue(result['activated'])
            original=result['active_revisions']
            with self.assertRaises(RuntimeError):run(args)
            args.action='activate'
            input_path.write_text(json.dumps({'expected':original,'values':{'content':{'WIZARD_DATA_SOURCE':'local','LOAN_DEMO_URL':'https://app.example.test/changed'}}}))
            changed=run(args)['active_revisions'];self.assertNotEqual(changed['content'],original['content'])
            args.action='restore';input_path.write_text(json.dumps({'expected':changed,'revisions':original}))
            self.assertEqual(run(args)['active_revisions'],original)
            with psycopg.connect(before['reader_dsn'],autocommit=True) as reader:
                self.assertEqual(reader.execute('select count(*) from runtime_config.active').fetchone()[0],3)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): reader.execute('select status from public.applications')

if __name__=='__main__': unittest.main()
