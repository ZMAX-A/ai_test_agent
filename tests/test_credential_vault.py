import unittest
from unittest.mock import patch

from config.settings import settings
from core.credential_vault import CredentialVault


class CredentialVaultTests(unittest.TestCase):
    def setUp(self):
        self.username = settings.LOGIN_USERNAME
        self.password = settings.LOGIN_PASSWORD
        settings.LOGIN_USERNAME = "vault-user"
        settings.LOGIN_PASSWORD = "vault-pass"
        self.vault = CredentialVault()

    def tearDown(self):
        settings.LOGIN_USERNAME = self.username
        settings.LOGIN_PASSWORD = self.password

    def test_model_text_uses_references_not_secrets(self):
        safe = self.vault.sanitize_text("输入 vault-user 和 vault-pass")
        self.assertEqual(
            safe,
            "输入 {{credential.username}} 和 {{credential.password}}",
        )

    def test_personal_contact_data_is_redacted_before_model_context(self):
        safe = self.vault.sanitize_text(
            "手机号 13800138000，邮箱 customer@example.com"
        )
        self.assertNotIn("13800138000", safe)
        self.assertNotIn("customer@example.com", safe)
        self.assertIn("{{redacted.phone}}", safe)
        self.assertIn("{{redacted.email}}", safe)

    def test_email_next_to_unicode_text_is_redacted(self):
        safe = self.vault.sanitize_text(
            "customer@example.com\u5df2\u767b\u8bb0"
        )
        self.assertNotIn("customer@example.com", safe)
        self.assertIn("{{redacted.email}}", safe)

    def test_named_and_url_tokens_are_redacted(self):
        with patch.object(
            settings,
            "get_credential",
            return_value={
                "username": "invalid-user",
                "password": "invalid-pass",
            },
        ):
            safe = self.vault.sanitize_text(
                "invalid-pass https://example.test/?access_token=url-secret "
                "Authorization: Bearer bearer-secret"
            )
        self.assertNotIn("invalid-pass", safe)
        self.assertNotIn("url-secret", safe)
        self.assertNotIn("bearer-secret", safe)
        self.assertIn("{{credential.invalid.password}}", safe)

    def test_real_values_are_injected_only_into_execution_copy(self):
        action = {
            "action": "fill",
            "parameters": {"role": "textbox", "value": "{{credential.password}}"},
        }
        resolved = self.vault.resolve_action(action)
        self.assertEqual(resolved["parameters"]["value"], "vault-pass")
        self.assertEqual(action["parameters"]["value"], "{{credential.password}}")

    def test_deterministic_action_is_tokenized_before_audit(self):
        action = {"action": "fill", "parameters": {"value": "vault-user"}}
        safe = self.vault.tokenize_action(action)
        self.assertEqual(safe["parameters"]["value"], "{{credential.username}}")

    def test_missing_named_credential_fails_closed(self):
        with self.assertRaises(RuntimeError):
            self.vault.resolve_text("{{credential.missing.password}}")


if __name__ == "__main__":
    unittest.main()
