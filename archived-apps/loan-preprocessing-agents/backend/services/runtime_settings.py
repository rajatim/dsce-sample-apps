"""Immutable request snapshots with bounded, on-demand refresh and failure grace."""
from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Mapping
import threading
import time
import logging
from services.runtime_crypto import ConfigurationUnavailable


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, repr=False)
class SettingsSnapshot:
    revisions: Mapping
    groups: Mapping = field(repr=False)
    values: Mapping = field(repr=False)

    @classmethod
    def create(cls, revisions, groups):
        if not groups or set(revisions) != set(groups):
            raise ConfigurationUnavailable()
        values = {}
        for group in groups.values():
            if not isinstance(group, Mapping) or values.keys() & group.keys():
                raise ConfigurationUnavailable()
            values.update(group)
        return cls(_freeze(dict(revisions)), _freeze(groups), _freeze(values))


class SettingsProvider:
    def __init__(self, read, *, clock=time.monotonic):
        self._read = read
        self._clock = clock
        self._lock = threading.Lock()
        self._snapshot = None
        self._last_success = float('-inf')
        self._last_attempt = float('-inf')

    def snapshot(self):
        with self._lock:
            now = self._clock()
            if now - self._last_attempt >= 5:
                self._last_attempt = now
                try:
                    revisions, groups = self._read()
                    candidate = SettingsSnapshot.create(revisions, groups)
                    self._snapshot = candidate
                    self._last_success = self._clock()
                except Exception:
                    logging.getLogger(__name__).warning("Runtime configuration refresh failed")
            if self._snapshot is not None and self._clock() - self._last_success < 60:
                return self._snapshot
            raise ConfigurationUnavailable() from None

# Bootstrap is resolved lazily: builds and liveness must not require the database.
import base64
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

_provider = None
_provider_lock = threading.Lock()
_context = ContextVar('loan_runtime_settings', default=None)


def _database_provider():
    global _provider
    with _provider_lock:
        if _provider is None:
            try:
                from repositories.runtime_settings import SettingsRepository
                from services.runtime_registry import validate_groups
                keyring = {name: base64.b64decode(value, validate=True) for name,value in json.loads(os.environ['CONFIG_KEYRING_JSON']).items()}
                if not keyring or any(len(key) != 32 for key in keyring.values()):
                    raise ConfigurationUnavailable()
                repository = SettingsRepository(os.environ['CONFIG_DATABASE_URL'], os.environ['CONFIG_ENVIRONMENT'], 'loan', keyring)
                allowed_hosts = set(json.loads(os.environ['CONFIG_ALLOWED_HOSTS']))
                allow_local = os.environ.get('CONFIG_ENVIRONMENT') == 'local'
                def read():
                    revisions, groups = repository.read()
                    validate_groups('loan', groups, allowed_hosts=allowed_hosts, allow_local=allow_local)
                    return revisions, groups
                _provider = SettingsProvider(read)
            except Exception:
                raise ConfigurationUnavailable() from None
        return _provider


def get_settings():
    pinned = _context.get()
    if pinned is not None:
        return pinned
    mode = os.environ.get('RUNTIME_CONFIG_MODE', 'environment')
    if mode == 'database':
        return _database_provider().snapshot()
    if mode != 'environment':
        raise ConfigurationUnavailable()
    from services.runtime_registry import groups_from_environment
    groups = groups_from_environment('loan', os.environ)
    return SettingsSnapshot.create({group:'environment' for group in groups}, groups)


@contextmanager
def settings_context(snapshot=None):
    selected = snapshot or get_settings()
    token = _context.set(selected)
    try:
        yield selected
    finally:
        _context.reset(token)


def pin_settings(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with settings_context():
            return function(*args, **kwargs)
    return wrapped
