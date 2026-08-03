import unittest

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
