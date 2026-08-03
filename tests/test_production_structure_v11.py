import inspect
from pathlib import Path
import unittest

import web_agent.commands as commands
import web_agent.final as legacy_final
from web_agent.auth import AuthenticationPolicy
from web_agent.browser import PolicyAwareBrowserExecutor
from web_agent.final_browser import FinalPolicyBrowserExecutor
from web_agent.keyboard_text_browser import KeyboardTextPolicyBrowserExecutor


class ProductionStructureV11Tests(unittest.TestCase):
    def test_no_module_shadows_a_same_named_package(self):
        project_root = Path(__file__).resolve().parents[1]
        collisions = []
        for package_name in ("web_agent", "core"):
            package_root = project_root / package_name
            for module in package_root.glob("*.py"):
                if (package_root / module.stem).is_dir():
                    collisions.append(str(module.relative_to(project_root)))
        self.assertEqual(collisions, [])

    def test_production_browser_has_one_implementation(self):
        self.assertEqual(
            PolicyAwareBrowserExecutor.__module__,
            "web_agent.browser.executor",
        )
        self.assertIs(FinalPolicyBrowserExecutor, PolicyAwareBrowserExecutor)
        self.assertIs(
            KeyboardTextPolicyBrowserExecutor,
            PolicyAwareBrowserExecutor,
        )

    def test_production_composition_uses_canonical_browser(self):
        dependencies = commands.production_dependencies(AuthenticationPolicy())

        class Page:
            url = "https://example.test/"

            def title(self):
                return "Home"

        executor = dependencies.browser_executor_factory(Page(), object())
        self.assertIs(type(executor), PolicyAwareBrowserExecutor)

    def test_legacy_final_cli_delegates_to_canonical_main(self):
        self.assertIs(legacy_final.main, commands.main)
        source = inspect.getsource(commands.main)
        self.assertIn("ProductionRegressionRunner", source)
        self.assertNotIn("GenericTestRunner", source)


if __name__ == "__main__":
    unittest.main()
