from pathlib import Path
import unittest


class RepositoryLayoutTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_root_has_no_python_entry_scripts(self):
        root_scripts = sorted(path.name for path in self.root.glob("*.py"))
        self.assertEqual(root_scripts, [])

    def test_production_documentation_is_grouped(self):
        self.assertTrue((self.root / "docs" / "ARCHITECTURE.md").is_file())
        self.assertTrue((self.root / "docs" / "RUNBOOK.md").is_file())
        self.assertTrue((self.root / "docs" / "archive" / "README.md").is_file())

    def test_diagnostics_use_the_production_namespace(self):
        login_source = (
            self.root / "scripts" / "diagnostics" / "login.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from web_agent.browser import PolicyAwareBrowserExecutor", login_source)
        self.assertNotIn("from ai_test", login_source)
        self.assertNotIn("from run_", login_source)

    def test_readme_only_advertises_the_canonical_cli(self):
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("python -m web_agent", readme)
        self.assertNotIn("python main.py", readme)
        self.assertNotIn("python run_", readme)


if __name__ == "__main__":
    unittest.main()
