import importlib.util
import unittest
from concurrent.futures import ThreadPoolExecutor
import threading
from services.runtime_crypto import ConfigurationUnavailable

MODULE = importlib.util.find_spec('services.runtime_settings')
if MODULE:
    from services.runtime_settings import SettingsProvider

class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MODULE, 'snapshot provider exists')
        self.now = 0
        self.value = {'auth': {'JWT_SECRET_KEY': 'first'}}
        self.fail = False
        self.reads = 0
        def read():
            self.reads += 1
            if self.fail:
                raise RuntimeError('private database connection details')
            return {'auth': str(self.reads)}, self.value
        self.provider = SettingsProvider(read, clock=lambda: self.now)

    def test_on_demand_refresh_and_pinned_immutable_snapshot(self):
        first = self.provider.snapshot()
        self.value = {'auth': {'JWT_SECRET_KEY': 'second'}}
        self.now = 4.99
        self.assertIs(self.provider.snapshot(), first)
        self.now = 5
        self.assertEqual(self.provider.snapshot().values['JWT_SECRET_KEY'], 'second')
        self.assertEqual(first.values['JWT_SECRET_KEY'], 'first')
        with self.assertRaises(TypeError):
            first.values['JWT_SECRET_KEY'] = 'changed'

    def test_failed_reads_never_extend_grace(self):
        first = self.provider.snapshot()
        self.fail = True
        for second in (5, 15, 59.99):
            self.now = second
            self.assertIs(self.provider.snapshot(), first)
        self.now = 60
        with self.assertRaisesRegex(ConfigurationUnavailable, '^Configuration unavailable$'):
            self.provider.snapshot()

    def test_cold_start_fails_without_environment_fallback(self):
        self.fail = True
        with self.assertRaises(ConfigurationUnavailable):
            self.provider.snapshot()

    def test_concurrent_requests_share_one_successful_read(self):
        barrier = threading.Barrier(8)
        def run(_):
            barrier.wait()
            return self.provider.snapshot()
        with ThreadPoolExecutor(max_workers=8) as executor:
            snapshots = list(executor.map(run, range(8)))
        self.assertEqual(self.reads, 1)
        self.assertTrue(all(snapshot is snapshots[0] for snapshot in snapshots))

if __name__ == '__main__':
    unittest.main()
