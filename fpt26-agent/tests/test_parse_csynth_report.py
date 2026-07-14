import json
import tempfile
import unittest
from pathlib import Path

from harness.wrapper.parse_csynth_report import build_report, discover_csynth_report, main


FIXTURE = Path(__file__).parent / "fixtures" / "sample_csynth.rpt"


class ParseCsynthReportTests(unittest.TestCase):
    def test_parse_fixture_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "vector_add" / "baseline_000"
            report_dir = run_dir / "reports"
            logs_dir = run_dir / "logs"
            report_dir.mkdir(parents=True)
            logs_dir.mkdir()
            report_path = report_dir / "top_csynth.rpt"
            report_path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            (logs_dir / "csim.stdout.log").write_text("INFO: [SIM 211-1] CSim done with 0 errors.\n", encoding="utf-8")
            (logs_dir / "synth.stdout.log").write_text("INFO: [HLS 200-2161] Finished Command csynth_design\n", encoding="utf-8")

            result = build_report(report_path, run_dir)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["task_id"], "vector_add")
        self.assertEqual(result["candidate_id"], "baseline_000")
        self.assertEqual(result["stages"]["csim"], "pass")
        self.assertEqual(result["stages"]["synth"], "pass")
        self.assertEqual(result["metrics"]["target_clock_ns"], 10.0)
        self.assertEqual(result["metrics"]["estimated_clock_ns"], 1.482)
        self.assertEqual(result["metrics"]["latency_cycles"], {"min": 18, "max": 18})
        self.assertEqual(result["metrics"]["ii"], 16)
        self.assertEqual(result["metrics"]["resources"], {"lut": 103, "ff": 12, "bram": 0, "dsp": 0})
        self.assertEqual(result["errors"], [])

    def test_missing_fields_are_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "task" / "candidate"
            report_dir = run_dir / "reports"
            report_dir.mkdir(parents=True)
            report_path = report_dir / "empty_csynth.rpt"
            report_path.write_text("== Vitis HLS Report for 'top' ==\n", encoding="utf-8")

            result = build_report(report_path, run_dir)

        self.assertIsNone(result["metrics"]["target_clock_ns"])
        self.assertIsNone(result["metrics"]["estimated_clock_ns"])
        self.assertIsNone(result["metrics"]["latency_cycles"]["min"])
        self.assertIsNone(result["metrics"]["latency_cycles"]["max"])
        self.assertIsNone(result["metrics"]["ii"])
        self.assertIsNone(result["metrics"]["resources"]["lut"])
        self.assertGreater(len(result["warnings"]), 0)

    def test_cli_writes_report_json_from_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "vector_add" / "baseline_001"
            report_dir = run_dir / "reports"
            report_dir.mkdir(parents=True)
            (report_dir / "top_csynth.rpt").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            exit_code = main(["--run-dir", str(run_dir)])

            data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["metrics"]["resources"]["lut"], 103)

    def test_discover_report_fails_for_missing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                discover_csynth_report(Path(tmp))


if __name__ == "__main__":
    unittest.main()
