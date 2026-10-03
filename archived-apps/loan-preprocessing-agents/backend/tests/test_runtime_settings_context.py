import unittest
from unittest.mock import patch
import services.runtime_settings as settings

class ContextTests(unittest.TestCase):
    def test_context_keeps_snapshot_while_new_operation_observes_update(self):
        self.assertTrue(hasattr(settings,'settings_context'), 'operation context exists')
        now=[0]
        values={'KEY':'old'}
        provider=settings.SettingsProvider(lambda: ({'auth': str(now[0])},{'auth':dict(values)}),clock=lambda:now[0])
        with patch.object(settings,'_provider',provider), patch.dict('os.environ',{'RUNTIME_CONFIG_MODE':'database'}):
            with settings.settings_context():
                self.assertEqual(settings.get_settings().values['KEY'],'old')
                now[0]=5; values['KEY']='new'
                self.assertEqual(settings.get_settings().values['KEY'],'old')
            self.assertEqual(settings.get_settings().values['KEY'],'new')
    def test_unknown_mode_and_missing_bootstrap_fail_closed(self):
        self.assertTrue(hasattr(settings,'get_settings'),'runtime bootstrap exists')
        with patch.dict('os.environ',{'RUNTIME_CONFIG_MODE':'typo'},clear=True):
            with self.assertRaises(settings.ConfigurationUnavailable): settings.get_settings()
        with patch.object(settings,'_provider',None), patch.dict('os.environ',{'RUNTIME_CONFIG_MODE':'database'},clear=True):
            with self.assertRaises(settings.ConfigurationUnavailable): settings.get_settings()

if __name__ == '__main__': unittest.main()
