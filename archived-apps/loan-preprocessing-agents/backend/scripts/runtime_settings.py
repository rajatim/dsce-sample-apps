"""Protected operator workflow. No secret values or credential arguments are printed."""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0,str(BACKEND_DIRECTORY))
from repositories.runtime_settings import SettingsRepository, RevisionConflict
from services.runtime_crypto import ConfigurationUnavailable
from services.runtime_registry import REGISTRY, groups_from_environment, validate_groups


def read_protected_json(path):
    if str(path) == '-':
        return json.load(sys.stdin)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise RuntimeError('Protected input required')
        return json.load(stream)


def candidate_groups(action, application, payload, current):
    if action == 'import':
        if current:
            raise RuntimeError('Configuration already initialized; use an expected-revision update')
        return groups_from_environment(application,payload)
    return payload



def build_discovery_session():
    """Match Node hostname verification for the POC's trusted CN-only certificate."""
    import ssl
    import requests
    class DiscoveryAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            context = ssl.create_default_context(cafile=os.environ.get('REQUESTS_CA_BUNDLE') or requests.certs.where())
            context.hostname_checks_common_name = True
            kwargs['ssl_context'] = context
            return super().init_poolmanager(*args, **kwargs)
    session = requests.Session()
    session.mount('https://', DiscoveryAdapter())
    return session


def validate_providers(application, groups, allowed_hosts):
    """Authentication/metadata checks only: no inference, Agent execution or email."""
    values = {name:value for group in groups.values() for name,value in group.items()}
    if application == 'loan':
        from services.status_checks import build_status_http_client, check_wxo, check_watsonx, check_cos
        from status_models import StatusValue
        from utils.cos_client import COSClient
        now = datetime.now(timezone.utc)
        with build_status_http_client() as http:
            results = [*check_wxo(values,http,now),check_watsonx(values,http,now),check_cos(lambda:COSClient.for_status_check(cos_endpoint=values['COS_ENDPOINT'],cos_api_key_id=values['COS_API_KEY_ID'],cos_instance_crn=values['COS_INSTANCE_CRN']),values['COS_BUCKET_NAME'],now)]
        if any(result.status != StatusValue.READY for result in results):
            raise ConfigurationUnavailable()
        return
    if values.get('AUTH_PROVIDER') in ('ivia','ibmid'):
        prefix = 'IVIA' if values['AUTH_PROVIDER'] == 'ivia' else 'IBMID'
        with build_discovery_session() as session:
            response = session.get(values[f'{prefix}_WELL_KNOWN'],timeout=(3,5),allow_redirects=False)
        if response.status_code != 200: raise ConfigurationUnavailable()
        document = response.json()
        from urllib.parse import urlsplit
        for field in ('authorization_endpoint','token_endpoint','jwks_uri'):
            url = urlsplit(document.get(field,''))
            if url.scheme != 'https' or url.username or url.password or url.hostname not in allowed_hosts: raise ConfigurationUnavailable()
        if prefix == 'IVIA' and document.get('issuer') != values['IVIA_ISSUER']: raise ConfigurationUnavailable()
    if values.get('WIZARD_DATA_SOURCE') == 'cos':
        from utils.cos_client import COSClient
        COSClient.for_status_check(cos_endpoint=values['ASSETS_COS_ENDPOINT'],cos_api_key_id=values['CLOUD_SERVICEID_KEY'],cos_instance_crn=values['ASSETS_COS_INSTANCE_ID']).head_bucket(values['ASSETS_COS_PRIV_BUCKET'])
    if values.get('EMAIL_HOST'):
        import smtplib, ssl
        port=int(values['EMAIL_PORT']);context=ssl.create_default_context()
        if port == 465:
            client=smtplib.SMTP_SSL(values['EMAIL_HOST'],port,timeout=5,context=context)
        else:
            client=smtplib.SMTP(values['EMAIL_HOST'],port,timeout=5)
            client.starttls(context=context)
        with client:
            if values.get('EMAIL_USER'): client.login(values['EMAIL_USER'],values.get('EMAIL_PASS',''))
            client.noop()


def make_repository(profile, *, reader=False):
    keyring = {key:base64.b64decode(value,validate=True) for key,value in profile['keyring'].items()}
    return SettingsRepository(profile['reader_dsn' if reader else 'dsn'],profile['environment'],profile['application'],keyring)


def run(args):
    profile = read_protected_json(args.profile)
    if profile['environment'] != args.environment or profile['application'] != args.application:
        raise RuntimeError('Operator target mismatch')
    repository = make_repository(profile)
    current = repository.revisions()
    if args.action == 'list':
        return {'environment':args.environment,'application':args.application,'active_revisions':current}
    if args.action == 'inventory':
        return {'groups':{group:list(fields) for group,fields in REGISTRY['applications'][args.application].items()},'active_revisions':current}
    if not args.input: raise RuntimeError('Protected input required')
    payload = read_protected_json(args.input)
    if args.action == 'restore':
        selected=payload['revisions']
        changes=repository.read(selected)[1]
    else:
        changes=candidate_groups(args.action,args.application,payload.get('values',{}),current)
    expected=payload.get('expected',{})
    if expected != current: raise RevisionConflict()
    groups=repository.read()[1] if current else {}
    groups.update(changes)
    policy=dict(allowed_hosts=set(profile['allowed_hosts']),allow_local=args.environment=='local')
    validate=lambda candidate: validate_groups(args.application,candidate,**policy)
    validate(groups)
    if args.schema_only:
        if not args.dry_run: raise RuntimeError('Schema-only validation cannot activate settings')
    else:
        validate_providers(args.application,groups,policy['allowed_hosts'])
    if args.action == 'validate' or args.dry_run:
        return {'validated':True,'activated':False,'active_revisions':current,'provider_checks':not args.schema_only}
    # This writer has SELECT(status) only on Loan applications; no business writes.
    if args.application == 'loan' and set(changes) & {'wxo','cos','watsonx'}:
        with repository.connect() as connection:
            if connection.execute("SELECT count(*) AS count FROM public.applications WHERE lower(trim(status)) IN ('pending','processing','retrying')").fetchone()['count']:
                raise RuntimeError('Active Loan runs prevent provider settings changes')
    old=repository.read()[1] if current else {}
    signing_name='NEXTAUTH_SECRET' if args.application=='dsce' else 'JWT_SECRET_KEY'
    invalidates_sessions=bool(current and old.get('auth',{}).get(signing_name) != groups['auth'].get(signing_name))
    if invalidates_sessions:
        print(json.dumps({'notice':'Signing-key change invalidates existing sessions'}),file=sys.stderr)
    if args.action != 'restore':
        selected=repository.stage(changes,expected,profile['active_key_id'],validate)
    # Read using the exact target application's restricted role before activation.
    reader=make_repository(profile,reader=True)
    readback=reader.read(selected)[1]
    validate(readback)
    if readback != groups: raise ConfigurationUnavailable()
    result=repository.activate_selection(selected,expected,validate)
    return {'validated':True,'activated':True,'active_revisions':result,'invalidates_sessions':invalidates_sessions}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inventory','list','import','validate','activate','restore'])
    parser.add_argument('--profile',required=True,help='Mode-0600 operator profile path')
    parser.add_argument('--environment',required=True)
    parser.add_argument('--application',required=True,choices=['dsce','loan'])
    parser.add_argument('--input',help='Mode-0600 JSON input path, or - for stdin')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--schema-only',action='store_true')
    args=parser.parse_args(argv)
    try:
        print(json.dumps(run(args)))
        return 0
    except RevisionConflict:
        print(json.dumps({'error':'revision_conflict'}),file=sys.stderr)
    except Exception:
        print(json.dumps({'error':'configuration_operation_failed','activated':False}),file=sys.stderr)
    return 1

if __name__ == '__main__': raise SystemExit(main())
