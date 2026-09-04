import unittest
from unittest.mock import Mock

from utils.cos_client import COSClient


class COSMetadataCheckTests(unittest.TestCase):
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
