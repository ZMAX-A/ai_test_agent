from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from web_agent.cli import _normalized_argv, build_parser
from web_agent.commands import run_benchmark, run_excel
from web_agent.evaluation import report_passed


def _case():
    return {
        "case_id": "customer-profile",
        "case_name": "Customer profile",
        "module": "customer",
        "start_url": "https://example.test",
        "preconditions": "",
        "expected": "url contains /customer",
        "_steps_parsed": ["Open customer profile"],
    }


def _result():
    return {
        "success": True,
        "results": [
            {
                "success": True,
                "msg": "verified",
                "verification": {
                    "passed": True,
                    "evidence": ["URL contains /customer"],
                },
            }
        ],
        "trace": [{"all_actions": [{"action": "goto"}], "agent_events": []}],
        "collaboration": {"model_calls": 1, "event_count": 4},
    }


class _Runner:
    def run_case(self, **_kwargs):
        return _result()


class BenchmarkCliTests(unittest.TestCase):
    def test_benchmark_is_a_first_class_command(self):
        self.assertEqual(_normalized_argv(["benchmark"]), ["benchmark"])
        args = build_parser().parse_args(["benchmark"])
        self.assertEqual(args.repeat, 2)
        self.assertEqual(args.output, "report/benchmarks/latest.json")

    @patch("web_agent.commands.create_runner", return_value=_Runner())
    @patch("web_agent.commands.load_excel_cases", return_value=[_case()])
    def test_run_excel_emits_measured_result(
        self, _load_cases, _create_runner
    ):
        observed = []
        with redirect_stdout(StringIO()):
            outputs = run_excel(
                "cases.xlsx",
                True,
                result_observer=lambda *args: observed.append(args),
                run_index=3,
            )
        self.assertEqual(len(outputs), 1)
        self.assertEqual(observed[0][0]["case_id"], "customer-profile")
        self.assertTrue(observed[0][1]["success"])
        self.assertGreaterEqual(observed[0][2], 0.0)
        self.assertEqual(observed[0][3], 3)

    def test_run_benchmark_repeats_cases_and_writes_report(self):
        def fake_run_excel(
            _filepath,
            _headless,
            result_observer=None,
            run_index=1,
            runner_factory=None,
        ):
            result_observer(_case(), _result(), 0.25, run_index)
            self.assertIsNotNone(runner_factory)
            return [_result()]

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "benchmark.json"
            with patch("web_agent.commands.run_excel", side_effect=fake_run_excel):
                with redirect_stdout(StringIO()):
                    report = run_benchmark(
                        "cases.xlsx",
                        True,
                        2,
                        str(target),
                        "baseline",
                    )
            self.assertTrue(target.is_file())

        summary = report["summary"]
        self.assertEqual(summary["total_runs"], 2)
        self.assertEqual(summary["repeated_case_count"], 1)
        self.assertEqual(summary["reproducibility_rate"], 1.0)
        self.assertTrue(report_passed(report))


    @patch("web_agent.commands.create_runner", side_effect=RuntimeError("boom"))
    @patch("web_agent.commands.load_excel_cases", return_value=[_case()])
    def test_run_excel_records_runner_exception(self, _load_cases, _create_runner):
        observed = []
        with redirect_stdout(StringIO()):
            outputs = run_excel(
                "cases.xlsx",
                True,
                result_observer=lambda *args: observed.append(args),
            )
        self.assertFalse(outputs[0]["success"])
        self.assertEqual(len(observed), 1)
        self.assertIn("RuntimeError: boom", observed[0][1]["results"][0]["msg"])

    def test_benchmark_writes_failure_report_when_suite_crashes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "benchmark.json"
            with patch(
                "web_agent.commands.run_excel",
                side_effect=RuntimeError("loader boom"),
            ):
                with redirect_stdout(StringIO()):
                    report = run_benchmark(
                        "cases.xlsx", True, 2, str(target), "baseline"
                    )
            self.assertTrue(target.is_file())
        self.assertFalse(report_passed(report))
        self.assertEqual(report["summary"]["failed_runs"], 1)
        self.assertIn(
            "RuntimeError: loader boom",
            report["records"][0]["error"],

        )

if __name__ == "__main__":
    unittest.main()
