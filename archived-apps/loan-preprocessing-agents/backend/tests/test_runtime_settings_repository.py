import importlib.util
import os
import unittest
from services.runtime_crypto import ConfigurationUnavailable

MODULE = importlib.util.find_spec('repositories.runtime_settings')
if MODULE:
    from repositories.runtime_settings import SettingsRepository, RevisionConflict

@unittest.skipUnless(os.getenv('RUNTIME_TEST_ADMIN_DSN'), 'explicit disposable database required')
class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MODULE, 'configuration repository exists')
        self.keyring = {'test-operator-key': bytes([8]) * 32}
        self.writer = SettingsRepository('postgresql://runtime_test_writer@/runtime_settings_test_20261003', 'test', 'loan', self.keyring)
        self.reader = SettingsRepository('postgresql://runtime_test_loan@/runtime_settings_test_20261003', 'test', 'loan', self.keyring)

    def test_atomic_batch_conflict_validation_and_restore(self):
        # Separate group names keep this fixture independent from role tests.
        # Seed auth from earlier role test uses a deliberately opaque ciphertext;
        # this test application uses a separate environment with the same role grants.
        import psycopg
        with psycopg.connect(os.environ['RUNTIME_TEST_ADMIN_DSN']) as admin:
            admin.execute("insert into runtime_config.principals values ('runtime_test_writer','repository','loan',true),('runtime_test_loan','repository','loan',false) on conflict do nothing")
        self.writer.environment = self.reader.environment = 'repository'
        initial = self.writer.revisions()
        validated = []
        result = self.writer.activate({'auth': {'JWT_SECRET_KEY': 'test-signing-secret'}, 'wxo': {'WXO_API_KEY': 'test-provider-key'}}, initial, 'test-operator-key', lambda groups: validated.append(set(groups)))
        revisions, groups = self.reader.read()
        self.assertEqual(revisions, result)
        self.assertEqual(validated, [{'auth', 'wxo'}, {'auth', 'wxo'}])
        self.assertEqual(groups['wxo']['WXO_API_KEY'], 'test-provider-key')
        with self.assertRaises(RevisionConflict):
            self.writer.activate({'auth': {'JWT_SECRET_KEY': 'stale'}}, initial, 'test-operator-key', lambda _: None)
        def invalid(_):
            raise ConfigurationUnavailable()
        with self.assertRaises(ConfigurationUnavailable):
            self.writer.activate({'auth': {'JWT_SECRET_KEY': 'invalid'}}, result, 'test-operator-key', invalid)
        self.assertEqual(self.reader.revisions(), result)
        with self.assertRaises(ConfigurationUnavailable):
            self.reader.activate({'auth': {'JWT_SECRET_KEY': 'forbidden'}}, result, 'test-operator-key', lambda _: None)
        changed = self.writer.activate({'auth': {'JWT_SECRET_KEY': 'new'}}, result, 'test-operator-key', lambda _: None)
        self.assertNotEqual(changed['auth'], result['auth'])
        self.assertEqual(changed['wxo'], result['wxo'])
        self.assertEqual(self.reader.read(result)[1]['auth']['JWT_SECRET_KEY'], 'test-signing-secret')

    def test_concurrent_operators_cannot_overwrite_each_other(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        self.writer.environment = 'repository'
        initial=self.writer.revisions()
        barrier=threading.Barrier(2)
        def activate(label):
            barrier.wait()
            try:
                return self.writer.activate({'auth':{'JWT_SECRET_KEY':label}},initial,'test-operator-key',lambda _:None)
            except RevisionConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(activate,['first-operator','second-operator']))
        self.assertEqual(sum(result is not None for result in results),1)
        self.assertIn(self.writer.revisions(),results)
        self.writer.activate_selection(initial,next(result for result in results if result is not None),lambda _:None)

if __name__ == '__main__': unittest.main()
