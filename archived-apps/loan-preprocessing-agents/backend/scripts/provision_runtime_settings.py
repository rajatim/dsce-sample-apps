"""Provision only the approved POC configuration roles; preserve existing credentials."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import base64
from urllib.parse import urlsplit,urlunsplit,quote
import psycopg
from psycopg import sql
BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))
from scripts.runtime_settings import read_protected_json

ROLES={'owner':'dsce_loan_cfg_owner','writer':'dsce_loan_cfg_writer','dsce':'dsce_cfg_reader','loan':'loan_cfg_reader'}


def protected_write(path,value):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as stream: json.dump(value,stream)


def role_url(url,user,password):
    parts=urlsplit(url)
    host=parts.hostname
    if ':' in host: host=f'[{host}]'
    if parts.port: host+=f':{parts.port}'
    return urlunsplit(('postgresql',f'{quote(user,safe="")}:{quote(password,safe="")}@{host}',parts.path,parts.query,''))


def provision(profile,directory,action):
    environment=profile['environment']
    database=profile['database']
    directory=Path(directory)
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    if directory.stat().st_mode & 0o077: raise RuntimeError('Protected output directory required')
    state_path=directory/'provision-state.json'
    has_primary_state = state_path.exists()
    if has_primary_state:
        state=read_protected_json(state_path)
        if state['environment']!=environment or state['database']!=database: raise RuntimeError('Target mismatch')
    else:
        if action!='roles': raise RuntimeError('Provision roles first')
        with psycopg.connect(profile['admin_dsn'],connect_timeout=5) as check:
            if check.execute('SELECT current_database()').fetchone()[0]!=database: raise RuntimeError('Target mismatch')
            if check.execute('SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)',(list(ROLES.values()),)).fetchone():
                raise RuntimeError('Primary role credentials missing')
        state={'environment':environment,'database':database,'passwords':{name:secrets.token_urlsafe(36) for name in ('writer','dsce','loan')}}
        protected_write(state_path,state)
    with psycopg.connect(profile['admin_dsn'],connect_timeout=5) as connection:
        if connection.execute('SELECT current_database()').fetchone()[0]!=database: raise RuntimeError('Target mismatch')
        if action=='roles':
            for name,role in ROLES.items():
                existing=connection.execute("SELECT rolsuper,rolbypassrls,rolcanlogin,rolcreatedb,rolcreaterole,rolreplication,shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s",(role,)).fetchone()
                if existing:
                    if not has_primary_state: raise RuntimeError('Primary role credentials missing')
                    if existing!=(False,False,name!='owner',False,False,False,f'runtime-config:{environment}:{database}'): raise RuntimeError('Existing role privileges differ')
                    # Never reset a pre-existing password. Test preserved credentials separately.
                    continue
                if name=='owner': connection.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role)))
                else: connection.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}').format(sql.Identifier(role),sql.Literal(state['passwords'][name])))
                connection.execute(sql.SQL('COMMENT ON ROLE {} IS {}').format(sql.Identifier(role),sql.Literal(f'runtime-config:{environment}:{database}')))
            connection.execute(sql.SQL('GRANT CREATE ON DATABASE {} TO {}').format(sql.Identifier(database),sql.Identifier(ROLES['owner'])))
            for app in ('dsce','loan'):
                output=directory/f'{app}-operator.json'
                if not output.exists():
                    key_id=f'{environment}-v1'
                    backup_path=directory/f'{app}-key-backup.json'
                    if backup_path.exists():
                        backup=read_protected_json(backup_path)
                        key=base64.b64decode(backup[key_id],validate=True)
                    else:
                        key=secrets.token_bytes(32)
                        backup={key_id:base64.b64encode(key).decode()}
                        protected_write(backup_path,backup)
                    restored=read_protected_json(backup_path)
                    from services.runtime_crypto import encrypt_settings,decrypt_settings
                    metadata=dict(environment=environment,application=app,group='backup-check',revision='00000000-0000-4000-8000-000000000001',schema_version=1,key_id=key_id)
                    encrypted=encrypt_settings(metadata,{'check':'non-secret backup check'},key)
                    assert decrypt_settings(encrypted,{key_id:base64.b64decode(restored[key_id])},metadata)=={'check':'non-secret backup check'}
                    protected_write(output,{'environment':environment,'application':app,'dsn':role_url(profile['runtime_url'],ROLES['writer'],state['passwords']['writer']),'reader_dsn':role_url(profile['runtime_url'],ROLES[app],state['passwords'][app]),'keyring':backup,'active_key_id':key_id,'allowed_hosts':profile['allowed_hosts'][app]})
            transaction_path=directory/'dsce-auth-transaction-key.json'
            if not transaction_path.exists(): protected_write(transaction_path,{'key':base64.b64encode(secrets.token_bytes(32)).decode()})
        else:
            for name in ('dsce','loan','writer'):
                role=ROLES[name]
                connection.execute(sql.SQL('GRANT USAGE ON SCHEMA runtime_config TO {}').format(sql.Identifier(role)))
                connection.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA runtime_config TO {}').format(sql.Identifier(role)))
                for app in (('dsce','loan') if name=='writer' else (name,)):
                    connection.execute('INSERT INTO runtime_config.principals(role_name,environment,application,can_write) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',(role,environment,app,name=='writer'))
            connection.execute(sql.SQL('GRANT INSERT ON runtime_config.revisions TO {}').format(sql.Identifier(ROLES['writer'])))
            connection.execute(sql.SQL('GRANT INSERT,UPDATE ON runtime_config.active TO {}').format(sql.Identifier(ROLES['writer'])))
            connection.execute(sql.SQL('GRANT SELECT(status) ON public.applications TO {}').format(sql.Identifier(ROLES['writer'])))
            for app in ('dsce','loan'):
                membership=connection.execute('SELECT pg_has_role(%s,%s,\'MEMBER\'),pg_has_role(%s,%s,\'MEMBER\')',(ROLES[app],ROLES['owner'],ROLES[app],ROLES['writer'])).fetchone()
                if any(membership): raise RuntimeError('Runtime role has excessive membership')
    return {'action':action,'environment':environment,'database':database,'roles':list(ROLES.values()),'completed':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['roles','grants'])
    parser.add_argument('--profile',required=True)
    parser.add_argument('--environment',required=True)
    parser.add_argument('--output-directory',required=True)
    args=parser.parse_args()
    try:
        profile=read_protected_json(args.profile)
        if profile['environment']!=args.environment: raise RuntimeError('Target mismatch')
        print(json.dumps(provision(profile,args.output_directory,args.action)))
        return 0
    except Exception:
        print(json.dumps({'error':'scoped_role_provisioning_failed'}))
        return 1

if __name__=='__main__': raise SystemExit(main())
