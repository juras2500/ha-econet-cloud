"""Authentication contracts observed in the current ecoNET application."""

import importlib
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

root = pathlib.Path(__file__).parents[1] / "custom_components" / "econet_cloud"
package = types.ModuleType("econet_auth_test_package")
package.__path__ = [str(root)]
sys.modules[package.__name__] = package
client = importlib.import_module(package.__name__ + ".client")


class AuthenticationTests(unittest.TestCase):
    def user(self):
        user = Mock()
        user.client.initiate_auth.return_value = {
            "ChallengeName": "PASSWORD_VERIFIER", "Session": "test-challenge-session",
            "ChallengeParameters": {"USER_ID_FOR_SRP": "test-user"},
        }
        user.client.respond_to_auth_challenge.return_value = {"AuthenticationResult": {
            "IdToken": "test-id", "AccessToken": "test-access", "RefreshToken": "test-refresh",
            "ExpiresIn": 3600,
        }}
        return user

    def test_login_supplies_app_metadata_and_preserves_challenge_session(self):
        user, srp = self.user(), Mock()
        srp.get_auth_params.return_value = {"USERNAME": "test-user", "SRP_A": "test-public-value"}
        srp.process_challenge.return_value = {"USERNAME": "test-user", "PASSWORD_CLAIM_SIGNATURE": "test-proof"}
        with patch.object(client, "_cognito", return_value=user), patch.object(client, "_srp", return_value=srp):
            session = client.login_sync("test-user", "test-password")
        self.assertEqual(user.client.initiate_auth.call_args.kwargs["ClientMetadata"], {"appId": "0"})
        self.assertEqual(user.client.respond_to_auth_challenge.call_args.kwargs["ClientMetadata"], {"appId": "0"})
        self.assertEqual(user.client.respond_to_auth_challenge.call_args.kwargs["Session"], "test-challenge-session")
        self.assertEqual(session["id_token"], "test-id")
        self.assertNotIn("password", session)
        self.assertEqual(user.verify_token.call_count, 2)

    def test_fresh_id_token_does_not_trigger_redundant_refresh(self):
        user, identity = self.user(), Mock()
        identity.get_id.return_value = {"IdentityId": "test-identity"}
        identity.get_credentials_for_identity.return_value = {"Credentials": {"test": True}}
        with patch.object(client, "_cognito", return_value=user), patch("boto3.client", return_value=identity):
            result = client.identity_sync("test-user", "test-refresh", initial_id_token="fresh-test-id")
        user.client.get_tokens_from_refresh_token.assert_not_called()
        user.client.initiate_auth.assert_not_called()
        self.assertEqual(result[2], "test-refresh")

    def test_refresh_supports_rotation_and_confirmed_device_key(self):
        user, identity = self.user(), Mock()
        user.client.get_tokens_from_refresh_token.return_value = {"AuthenticationResult": {
            "IdToken": "new-id", "AccessToken": "new-access", "RefreshToken": "rotated-refresh"}}
        identity.get_id.return_value = {"IdentityId": "test-identity"}
        identity.get_credentials_for_identity.return_value = {"Credentials": {"test": True}}
        with patch.object(client, "_cognito", return_value=user), patch("boto3.client", return_value=identity):
            result = client.identity_sync("test-user", "old-refresh", "test-device-key")
        args = user.client.get_tokens_from_refresh_token.call_args.kwargs
        self.assertEqual(args["DeviceKey"], "test-device-key")
        self.assertEqual(args["ClientMetadata"], {"appId": "0"})
        self.assertEqual(result[2], "rotated-refresh")
        user.client.initiate_auth.assert_not_called()

    def test_data_authorization_failure_is_not_labeled_bad_password(self):
        class Rejected(Exception):
            response = {"Error": {"Code": "NotAuthorizedException", "Message": "FAKE-PRIVATE-DETAIL"}}
        with self.assertLogs(client.LOGGER, level="WARNING") as logs:
            error = client._safe_auth_error(Rejected(), "identity")
        self.assertEqual(error.stage, "identity")
        self.assertNotIn("FAKE-PRIVATE-DETAIL", str(error) + str(logs.output))

    def test_additional_challenge_is_not_labeled_bad_password(self):
        user, srp = self.user(), Mock()
        user.client.respond_to_auth_challenge.return_value = {"ChallengeName": "SMS_MFA"}
        with self.assertRaises(client.AuthError) as caught:
            client._authenticate_srp(user, srp)
        self.assertEqual(caught.exception.stage, "challenge")


if __name__ == "__main__":
    unittest.main()
