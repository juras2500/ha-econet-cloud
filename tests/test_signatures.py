"""Compare authentication bytes with independent AWS/Node implementations."""

from datetime import datetime, timezone
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "custom_components" / "econet_cloud"))
from protocol import signed_headers, websocket_url

try:
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials
except ImportError:
    SigV4Auth = None

NOW = datetime(2026, 11, 22, 22, tzinfo=timezone.utc)
CREDS = {"AccessKeyId": "AKIDEXAMPLE", "SecretKey": "example-test-secret", "SessionToken": "example/test+token="}


class SignatureTests(unittest.TestCase):
    def test_iot_matches_reviewed_node_client(self):
        reference = json.loads(pathlib.Path(__file__).with_name("iot-signature-reference.json").read_text())
        actual = websocket_url("wss://example-ats.iot.eu-central-1.amazonaws.com/mqtt", CREDS, "eu-central-1", NOW)
        self.assertEqual(actual, reference["expected"])

    @unittest.skipIf(SigV4Auth is None, "botocore is available in the integration's dependency environment")
    def test_profile_request_matches_botocore_including_escaped_path(self):
        url = "https://example.execute-api.eu-central-1.amazonaws.com/prod/v1/profiles/139/ecoVENT%20MINI%20OEM/H3.4.0/S001.34/web/profile.json"
        request = AWSRequest(method="GET", url=url, headers={"appid": "0", "content-type": "application/json"})
        with patch("botocore.auth.get_current_datetime", return_value=NOW):
            SigV4Auth(Credentials(CREDS["AccessKeyId"], CREDS["SecretKey"], CREDS["SessionToken"]), "execute-api", "eu-central-1").add_auth(request)
        self.assertEqual(signed_headers(url, CREDS, "eu-central-1", NOW)["Authorization"], request.headers["Authorization"])


if __name__ == "__main__":
    unittest.main()
