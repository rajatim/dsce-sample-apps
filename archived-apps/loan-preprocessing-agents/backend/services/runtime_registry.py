"""Allowlisted runtime settings; URL trust boundaries remain bootstrap policy."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from services.runtime_crypto import ConfigurationUnavailable

REGISTRY = json.loads(Path(__file__).with_suffix('.json').read_text())


def groups_from_environment(application, environment):
    return {group: {name: environment.get(name, spec.get('default', '')) for name, spec in fields.items()} for group, fields in REGISTRY['applications'][application].items()}


def validate_groups(application, groups, *, allowed_hosts, allow_local=False):
    try:
        registry = REGISTRY['applications'][application]
        if set(groups) != set(registry):
            raise ValueError()
        values = {}
        for group, fields in registry.items():
            if set(groups[group]) - set(fields):
                raise ValueError()
            for name, value in groups[group].items():
                spec = fields[name]
                if not isinstance(value, str) or len(value) > 16384 or '\x00' in value:
                    raise ValueError()
                if value and 'enum' in spec and value not in spec['enum']:
                    raise ValueError()
                if value and spec.get('url'):
                    url = urlsplit(value)
                    local = allow_local and url.hostname in ('localhost','127.0.0.1','::1') and url.scheme == 'http'
                    if (url.scheme != 'https' and not local) or url.username or url.password or url.fragment or url.hostname not in allowed_hosts:
                        raise ValueError()
                    if url.port and url.port != 443 and not local:
                        raise ValueError()
                values[name] = value
        required = ['NEXTAUTH_SECRET','NEXTAUTH_URL','AUTH_PROVIDER','WIZARD_DATA_SOURCE'] if application == 'dsce' else ['JWT_SECRET_KEY','WXO_API_KEY','WXO_INSTANCE_ID','WXO_INSTANCE_CLOUD','DOC_PROCESSOR_AGENT_ID','DOCUMENT_VALIDATION_AGENT_ID','FINAL_DECISION_AGENT_ID','WATSONX_APIKEY','WATSONX_PROJECT_ID','WATSONX_URL','COS_ENDPOINT','COS_BUCKET_NAME','COS_API_KEY_ID','COS_INSTANCE_CRN']
        if application == 'dsce':
            provider = values.get('AUTH_PROVIDER')
            if provider == 'ivia': required += ['IVIA_CLIENT_ID','IVIA_CLIENT_SECRET','IVIA_ISSUER','IVIA_WELL_KNOWN','IVIA_TOKEN_ENDPOINT_AUTH_METHOD']
            if provider == 'ibmid': required += ['IBMID_CLIENT_ID','IBMID_CLIENT_SECRET','IBMID_WELL_KNOWN']
            if values.get('WIZARD_DATA_SOURCE') == 'cos': required += ['ASSETS_COS_ENDPOINT','ASSETS_COS_INSTANCE_ID','ASSETS_COS_PRIV_BUCKET','CLOUD_SERVICEID_KEY']
            if values.get('EMAIL_HOST'):
                required += ['EMAIL_PORT','EMAIL_FROM','EMAIL_TO']
                if values['EMAIL_HOST'] not in allowed_hosts or not 1 <= int(values.get('EMAIL_PORT','0')) <= 65535: raise ValueError()
                if any('\r' in values.get(k,'') or '\n' in values.get(k,'') for k in ('EMAIL_FROM','EMAIL_TO','EMAIL_HOST')): raise ValueError()
        elif values.get('WXO_INSTANCE_CLOUD') == 'cpd': required += ['WXO_SERVICE_INSTANCE_URL','WXO_CPD_USERNAME']
        if any(not values.get(name, '').strip() for name in required): raise ValueError()
        signing_key = values.get('NEXTAUTH_SECRET' if application == 'dsce' else 'JWT_SECRET_KEY','')
        if len(signing_key) < 32: raise ValueError()
        return groups
    except Exception:
        raise ConfigurationUnavailable() from None
