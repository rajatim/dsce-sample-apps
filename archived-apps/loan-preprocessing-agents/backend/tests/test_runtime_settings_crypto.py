"""Encrypted settings must reject changes to values and their owning scope."""
import unittest
import importlib.util

MODULE = importlib.util.find_spec('services.runtime_crypto')
if MODULE:
    from services.runtime_crypto import encrypt_settings, decrypt_settings, ConfigurationUnavailable

class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MODULE, 'runtime encryption module exists')
        self.metadata = dict(environment='test', application='loan', group='wxo', revision='00000000-0000-4000-8000-000000000001', schema_version=1, key_id='test-key')
        self.key = bytes([7]) * 32

    def test_roundtrip_random_nonce_no_plaintext(self):
        record = encrypt_settings(self.metadata, {'secret': 'test-only-secret'}, self.key)
        self.assertNotIn('test-only-secret', str(record))
        self.assertEqual(decrypt_settings(record, {'test-key': self.key}, self.metadata), {'secret': 'test-only-secret'})
        self.assertNotEqual(record['nonce'], encrypt_settings(self.metadata, {}, self.key)['nonce'])

    def test_tampering_key_scope_and_schema_fail_safely(self):
        record = encrypt_settings(self.metadata, {'secret': 'test-only-secret'}, self.key)
        for field in ('environment', 'application', 'group', 'revision', 'key_id', 'ciphertext', 'schema_version'):
            with self.subTest(field=field), self.assertRaisesRegex(ConfigurationUnavailable, '^Configuration unavailable$'):
                decrypt_settings({**record, field: 'wrong'}, {'test-key': self.key}, self.metadata)
        with self.assertRaises(ConfigurationUnavailable):
            decrypt_settings(record, {'test-key': bytes(32)}, self.metadata)
        with self.assertRaises(ConfigurationUnavailable):
            decrypt_settings(record, {'test-key': self.key}, {**self.metadata, 'application': 'dsce'})
        with self.assertRaises(ConfigurationUnavailable):
            encrypt_settings(self.metadata, {}, bytes(16))

if __name__ == '__main__':
    unittest.main()

class CrossLanguageVectorTests(unittest.TestCase):
    def test_node_and_python_vectors(self):
        import json, base64
        from pathlib import Path
        vector = json.loads((Path(__file__).parent / 'fixtures/envelope-v1.json').read_text())
        for record in (vector['record'], vector['python_record']):
            self.assertEqual(decrypt_settings(record, {'test-key': base64.b64decode(vector['key'])}, record), vector['expected'])
