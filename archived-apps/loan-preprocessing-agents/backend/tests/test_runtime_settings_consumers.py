import unittest
from types import SimpleNamespace
from unittest.mock import patch
from services.runtime_settings import SettingsSnapshot, settings_context
from utils import agents
from utils.cos_client import COSClient
import security
from jose import jwt

class ConsumerTests(unittest.TestCase):
    def snapshot(self, suffix):
        return SettingsSnapshot.create({'wxo':suffix,'auth':suffix,'cos':suffix}, {'wxo':{'WXO_INSTANCE_CLOUD':'cpd','WXO_SERVICE_INSTANCE_URL':f'https://{suffix}.example.test/orchestrate/instances/123','WXO_CPD_USERNAME':f'user-{suffix}','WXO_API_KEY':f'key-{suffix}'},'auth':{'JWT_SECRET_KEY':suffix*32},'cos':{'COS_ENDPOINT':f'https://{suffix}.example.test','COS_API_KEY_ID':f'cos-{suffix}','COS_INSTANCE_CRN':'test-crn'}})
    def test_actual_cpd_exchange_uses_current_snapshot_endpoint_and_identity(self):
        calls=[]
        def transport(url, **kwargs):
            calls.append((url,kwargs['json']))
            return SimpleNamespace(status_code=200,json=lambda:{'token':'test-token'})
        with patch.object(agents.requests,'post',side_effect=transport):
            for suffix in ('first','second'):
                with settings_context(self.snapshot(suffix)):
                    agents.get_bearer_token(f'key-{suffix}')
        self.assertEqual(calls,[(f'https://{suffix}.example.test/icp4d-api/v1/authorize',{'username':f'user-{suffix}','api_key':f'key-{suffix}'}) for suffix in ('first','second')])
    def test_cos_factory_uses_current_snapshot(self):
        with settings_context(self.snapshot('current')), patch('utils.cos_client.ibm_boto3.client') as factory:
            COSClient()
            self.assertEqual(factory.call_args.kwargs['ibm_api_key_id'],'cos-current')
            self.assertEqual(factory.call_args.kwargs['endpoint_url'],'https://current.example.test')
    def test_token_signing_uses_snapshot_secret(self):
        with settings_context(self.snapshot('current')):
            token=security.create_access_token({'sub':'test-user'})
        self.assertEqual(jwt.decode(token,'current'*32,algorithms=['HS256'])['sub'],'test-user')

    def test_cached_cos_factory_does_not_keep_old_revision(self):
        import main
        with patch('utils.cos_client.ibm_boto3.client') as factory:
            for suffix in ('first','second'):
                with settings_context(self.snapshot(suffix)):
                    main.get_cos_client()
                    self.assertEqual(factory.call_args.kwargs['ibm_api_key_id'],f'cos-{suffix}')
    def test_watsonx_constructor_uses_snapshot_instead_of_default_arguments(self):
        from services.watsonx import watsonx_chat_model
        snapshot = SettingsSnapshot.create({'watsonx':'test'}, {'watsonx':{'WATSONX_APIKEY':'test-key','WATSONX_PROJECT_ID':'test-project','WATSONX_URL':'https://test.example'}})
        with settings_context(snapshot), patch('services.watsonx.ChatWatsonxWithRetry') as factory:
            watsonx_chat_model()
            self.assertEqual(factory.call_args.kwargs['apikey'],'test-key')
    def test_database_mode_does_not_persist_raw_provider_errors(self):
        from repositories.application_records import _safe_error_text
        with patch.dict('os.environ', {'RUNTIME_CONFIG_MODE':'database'}):
            self.assertEqual(_safe_error_text('old-revision-secret provider body'),'Application processing failed. Review the dependency status.')

    def test_explicit_operator_cos_credentials_do_not_require_app_bootstrap(self):
        with patch.dict('os.environ',{'RUNTIME_CONFIG_MODE':'database'},clear=True), patch('utils.cos_client.ibm_boto3.client') as factory:
            COSClient(cos_endpoint='https://test.example',cos_api_key_id='test-key',cos_instance_crn='test-crn')
            self.assertEqual(factory.call_args.kwargs['ibm_api_key_id'],'test-key')

if __name__ == '__main__': unittest.main()
