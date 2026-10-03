"""Scoped encrypted configuration reads and transactional operator activation."""
import base64
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from services.runtime_crypto import ConfigurationUnavailable, encrypt_settings, decrypt_settings


class RevisionConflict(RuntimeError):
    def __init__(self):
        super().__init__('Configuration revision changed; read current metadata and retry')


class SettingsRepository:
    def __init__(self, dsn, environment, application, keyring):
        self._dsn = dsn
        self.environment = environment
        self.application = application
        self._keyring = keyring

    def connect(self):
        return psycopg.connect(self._dsn, connect_timeout=3, options='-c statement_timeout=3000 -c lock_timeout=3000', row_factory=dict_row)

    def _revisions(self, connection):
        rows = connection.execute('SELECT group_name,revision FROM runtime_config.active WHERE environment=%s AND application=%s', (self.environment, self.application)).fetchall()
        return {r['group_name']: str(r['revision']) for r in rows}

    def revisions(self):
        try:
            with self.connect() as connection:
                return self._revisions(connection)
        except Exception:
            raise ConfigurationUnavailable() from None

    def _read(self, connection, revisions):
        groups = {}
        for group, revision in revisions.items():
            row = connection.execute('SELECT environment,application,group_name,revision,schema_version,key_id,nonce,ciphertext FROM runtime_config.revisions WHERE environment=%s AND application=%s AND group_name=%s AND revision=%s', (self.environment, self.application, group, revision)).fetchone()
            if row is None:
                raise ConfigurationUnavailable()
            record = {**row, 'group': row['group_name'], 'revision': str(row['revision']), 'nonce': base64.b64encode(row['nonce']).decode(), 'ciphertext': base64.b64encode(row['ciphertext']).decode()}
            expected = {**record, 'environment': self.environment, 'application': self.application, 'group': group, 'revision': revision, 'schema_version': 1}
            groups[group] = decrypt_settings(record, self._keyring, expected)
        return groups

    def read(self, revisions=None):
        try:
            with self.connect() as connection:
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                selected = self._revisions(connection) if revisions is None else dict(revisions)
                return selected, self._read(connection, selected)
        except Exception:
            raise ConfigurationUnavailable() from None

    def stage(self, changes, expected, key_id, validate):
        """Validate a full snapshot, then install all changed groups in one commit."""
        try:
            with self.connect() as connection:
                connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'runtime_config:{self.environment}:{self.application}',))
                current = self._revisions(connection)
                if current != expected:
                    raise RevisionConflict()
                groups = self._read(connection, current)
                groups.update(changes)
                validate(groups)
                result = dict(current)
                for group, values in changes.items():
                    revision = str(uuid4())
                    metadata = dict(environment=self.environment, application=self.application, group=group, revision=revision, schema_version=1, key_id=key_id)
                    record = encrypt_settings(metadata, values, self._keyring[key_id])
                    connection.execute('INSERT INTO runtime_config.revisions(environment,application,group_name,revision,schema_version,key_id,nonce,ciphertext) VALUES (%s,%s,%s,%s,1,%s,%s,%s)', (self.environment,self.application,group,revision,key_id,base64.b64decode(record['nonce']),base64.b64decode(record['ciphertext'])))
                    # Verify the exact persisted candidate before pointing readers at it.
                    if self._read(connection, {group: revision})[group] != values:
                        raise ConfigurationUnavailable()
                    result[group] = revision
                return result
        except RevisionConflict:
            raise
        except Exception:
            raise ConfigurationUnavailable() from None

    def activate_selection(self, selected, expected, validate):
        try:
            with self.connect() as connection:
                connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'runtime_config:{self.environment}:{self.application}',))
                current = self._revisions(connection)
                if current != expected:
                    raise RevisionConflict()
                if set(current) - set(selected):
                    raise ConfigurationUnavailable()
                validate(self._read(connection, selected))
                for group, revision in selected.items():
                    if current.get(group) != revision:
                        connection.execute('INSERT INTO runtime_config.active(environment,application,group_name,revision) VALUES (%s,%s,%s,%s) ON CONFLICT (environment,application,group_name) DO UPDATE SET revision=EXCLUDED.revision', (self.environment,self.application,group,revision))
                return dict(selected)
        except RevisionConflict:
            raise
        except Exception:
            raise ConfigurationUnavailable() from None

    def activate(self, changes, expected, key_id, validate):
        selected = self.stage(changes, expected, key_id, validate)
        return self.activate_selection(selected, expected, validate)
