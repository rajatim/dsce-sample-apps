import unittest
from unittest.mock import Mock, patch

from utils.cos_client import COSClient


class COSMetadataCheckTests(unittest.TestCase):
    @patch("utils.cos_client.ibm_boto3.client")
    def test_status_client_has_short_deadlines_and_no_retries(self, create_client):
        COSClient.for_status_check(
            cos_endpoint="https://cos.example",
            cos_api_key_id="test-key",
            cos_instance_crn="test-crn",
        )

        config = create_client.call_args.kwargs["config"]
        self.assertEqual(config.connect_timeout, 1)
        self.assertEqual(config.read_timeout, 2)
        self.assertEqual(config.retries, {"max_attempts": 0, "mode": "standard"})

    def test_head_bucket_is_read_only_and_does_not_swallow_errors(self):
        sdk = Mock()
        client = object.__new__(COSClient)
        client._cos = sdk

        client.head_bucket("loan-demo")

        sdk.head_bucket.assert_called_once_with(Bucket="loan-demo")

    def test_head_bucket_propagates_sdk_failure(self):
        sdk = Mock()
        sdk.head_bucket.side_effect = RuntimeError("secret provider response")
        client = object.__new__(COSClient)
        client._cos = sdk

        with self.assertRaisesRegex(RuntimeError, "secret provider response"):
            client.head_bucket("loan-demo")


if __name__ == "__main__":
    unittest.main()
