import inspect
import unittest

from web_agent.auth import AuthenticationPolicy
from web_agent.browser import PolicyAwareBrowserExecutor
from web_agent.cli import _normalized_argv
from web_agent.runner import (
    FORMAL_AGENTS,
    ProductionRunner,
    default_dependencies,
    filter_login_setup_trace,
)


class WebAgentArchitectureTests(unittest.TestCase):
    def test_runner_has_one_registered_source_module(self):
        module = inspect.getmodule(ProductionRunner)
        self.assertIsNotNone(module)
        self.assertEqual(module.__name__, "web_agent.runner")
        source = inspect.getsource(module)
        self.assertNotIn("spec_from_file_location", source)
        self.assertNotIn("exec_module", source)

    def test_browser_executor_is_explicit_dependency(self):
        dependencies = default_dependencies(AuthenticationPolicy())
        executor = dependencies.browser_executor_factory
        self.assertTrue(callable(executor))
        runner_source = inspect.getsource(ProductionRunner.run_case)
        self.assertIn("browser_executor_factory", runner_source)
        self.assertNotIn("SecurePlaywrightExecutor", runner_source)

    def test_formal_agent_permissions_are_minimal(self):
        manifest = ProductionRunner(headless=True).capability_manifest()
        self.assertEqual(set(manifest), set(FORMAL_AGENTS))
        self.assertEqual(manifest["critic"], [])
        self.assertEqual(manifest["replanner"], [])
        self.assertIn("click", manifest["executor"])
        self.assertNotIn("click", manifest["verifier"])

    def test_som_cleanup_does_not_delete_dom_nodes(self):
        source = inspect.getsource(ProductionRunner._clean_som_marks)
        self.assertIn("removeAttribute", source)
        self.assertNotIn("element.remove()", source)

    def test_login_trace_filter_uses_readable_keywords(self):
        trace = [
            {"goal": "点击登录按钮"},
            {"goal": "进入顾客档案"},
        ]
        filtered = filter_login_setup_trace(trace, "已登录")
        self.assertEqual(filtered, [{"goal": "进入顾客档案"}])

    def test_cli_defaults_to_explore_without_attribute_bug(self):
        self.assertEqual(_normalized_argv([]), ["explore"])
        self.assertEqual(
            _normalized_argv(["--headless"]),
            ["explore", "--headless"],
        )

    def test_policy_executor_is_the_default_browser_tool(self):
        dependencies = default_dependencies(AuthenticationPolicy())

        class Page:
            url = "https://example.test/"

            def title(self):
                return "Home"

        instance = dependencies.browser_executor_factory(Page(), object())
        self.assertIsInstance(instance, PolicyAwareBrowserExecutor)


if __name__ == "__main__":
    unittest.main()
