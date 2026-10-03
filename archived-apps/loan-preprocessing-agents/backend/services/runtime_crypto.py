"""Version 1 settings envelope shared with DSCE's Node crypto implementation."""
import base64
import json
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FIELDS = ('environment', 'application', 'group', 'revision', 'schema_version', 'key_id')

class ConfigurationUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Configuration unavailable')


def _aad(record):
    if type(record['schema_version']) is not int or record['schema_version'] != 1 or record['application'] not in ('dsce', 'loan'):
        raise ConfigurationUnavailable()
    if any(not isinstance(record[f], str) or not record[f] for f in FIELDS if f != 'schema_version'):
        raise ConfigurationUnavailable()
    return json.dumps(['runtime-config', 1, *(record[f] for f in FIELDS)], ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def encrypt_settings(metadata, values, key):
    try:
        if not isinstance(key, bytes) or len(key) != 32 or not isinstance(values, dict):
            raise ConfigurationUnavailable()
        record = {f: metadata[f] for f in FIELDS}
        nonce = secrets.token_bytes(12)
        payload = json.dumps(values, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        ciphertext = AESGCM(key).encrypt(nonce, payload, _aad(record))
        return {**record, 'nonce': base64.b64encode(nonce).decode('ascii'), 'ciphertext': base64.b64encode(ciphertext).decode('ascii')}
    except Exception:
        raise ConfigurationUnavailable() from None


def decrypt_settings(record, keyring, expected):
    try:
        if any(record[f] != expected[f] for f in FIELDS):
            raise ConfigurationUnavailable()
        key = keyring[record['key_id']]
        nonce = base64.b64decode(record['nonce'], validate=True)
        ciphertext = base64.b64decode(record['ciphertext'], validate=True)
        if not isinstance(key, bytes) or len(key) != 32 or len(nonce) != 12:
            raise ConfigurationUnavailable()
        values = json.loads(AESGCM(key).decrypt(nonce, ciphertext, _aad(record)).decode('utf-8'))
        if not isinstance(values, dict):
            raise ConfigurationUnavailable()
        return values
    except Exception:
        raise ConfigurationUnavailable() from None
