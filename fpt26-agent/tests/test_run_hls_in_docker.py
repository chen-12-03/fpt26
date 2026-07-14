import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = AGENT_ROOT / "harness" / "wrapper" / "run-hls-in-docker.sh"
WRAPPER_DIR = AGENT_ROOT / "harness" / "wrapper"
FIXTURE = AGENT_ROOT / "tests" / "fixtures" / "sample_csynth.rpt"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class RunHlsInDockerTests(unittest.TestCase):
    def run_runner(self, args, *, env=None, cwd=AGENT_ROOT):
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        return subprocess.run(
            [str(RUNNER), *args],
            cwd=cwd,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_missing_required_argument_fails_before_run(self):
        result = self.run_runner(
            [
                "--task-id",
                "vector_add",
                "--candidate-prefix",
                "baseline",
                "--top",
                "vector_add",
                "--source",
                "benchmarks/public/vector_add/kernel.cpp",
                "--testbench",
                "benchmarks/public/vector_add/host.cpp",
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required argument", result.stderr)
        self.assertIn("HLS_CLOCK_PERIOD_NS", result.stderr)

    def test_missing_source_fails_before_run(self):
        result = self.run_runner(
            [
                "--task-id",
                "vector_add",
                "--candidate-prefix",
                "baseline",
                "--top",
                "vector_add",
                "--source",
                "does-not-exist.cpp",
                "--testbench",
                "benchmarks/public/vector_add/host.cpp",
                "--clock-period",
                "10",
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source file does not exist", result.stderr)

    def test_missing_testbench_fails_before_run(self):
        result = self.run_runner(
            [
                "--task-id",
                "vector_add",
                "--candidate-prefix",
                "baseline",
                "--top",
                "vector_add",
                "--source",
                "benchmarks/public/vector_add/kernel.cpp",
                "--testbench",
                "does-not-exist.cpp",
                "--clock-period",
                "10",
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("testbench file does not exist", result.stderr)

    def test_invalid_clock_period_fails_before_run(self):
        result = self.run_runner(
            [
                "--task-id",
                "vector_add",
                "--candidate-prefix",
                "baseline",
                "--top",
                "vector_add",
                "--source",
                "benchmarks/public/vector_add/kernel.cpp",
                "--testbench",
                "benchmarks/public/vector_add/host.cpp",
                "--clock-period",
                "fast",
            ]
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid clock period", result.stderr)

    def test_existing_run_dir_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "existing"
            run_dir.mkdir()
            result = self.run_runner(
                [
                    "--task-id",
                    "vector_add",
                    "--candidate-prefix",
                    "baseline",
                    "--top",
                    "vector_add",
                    "--source",
                    "benchmarks/public/vector_add/kernel.cpp",
                    "--testbench",
                    "benchmarks/public/vector_add/host.cpp",
                    "--clock-period",
                    "10",
                ],
                env={"RUN_DIR": str(run_dir)},
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RUN_DIR already exists", result.stderr)

    def test_fake_tool_flow_writes_manifest_and_report_core_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = tmp_path / "bin"
            run_root = tmp_path / "runs" / "vector_add"
            fake_bin.mkdir()

            _write_executable(
                fake_bin / "vivado",
                "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
            )
            _write_executable(
                fake_bin / "vitis-run",
                f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "${{RUN_SYNTH:-0}}" != "0" ]]; then
  mkdir -p "$RUN_PROJECT_DIR/solution1/syn/report"
  cp "{FIXTURE}" "$RUN_PROJECT_DIR/solution1/syn/report/top_csynth.rpt"
  echo "INFO: [HLS 200-2161] Finished Command csynth_design"
else
  echo "INFO: [SIM 211-1] CSim done with 0 errors."
fi
""",
            )

            result = self.run_runner(
                [
                    "--task-id",
                    "vector_add",
                    "--candidate-prefix",
                    "baseline",
                    "--top",
                    "vector_add",
                    "--source",
                    "benchmarks/public/vector_add/kernel.cpp",
                    "--testbench",
                    "benchmarks/public/vector_add/host.cpp",
                    "--clock-period",
                    "10.0",
                ],
                env={
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                    "RUN_ROOT": str(run_root),
                },
            )

            run_dir = run_root / "baseline_000"
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(manifest["task_id"], "vector_add")
        self.assertEqual(manifest["candidate_prefix"], "baseline")
        self.assertEqual(manifest["kernel_entry"], "vector_add")
        self.assertEqual(manifest["hls_clock_period_ns"], "10.0")
        self.assertEqual(manifest["stages"], {"csim": "pass", "synth": "pass", "report": "pass", "cosim": "not_run"})
        self.assertEqual(manifest["final_exit_code"], 0)
        self.assertTrue(manifest["artifacts"]["csynth_report"].endswith("reports/top_csynth.rpt"))
        self.assertTrue(manifest["artifacts"]["report_json"].endswith("report.json"))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["task_id"], "vector_add")
        self.assertEqual(report["candidate_id"], "baseline_000")
        self.assertEqual(report["metrics"]["target_clock_ns"], 10.0)
        self.assertEqual(report["metrics"]["estimated_clock_ns"], 1.482)
        self.assertEqual(report["metrics"]["latency_cycles"], {"min": 18, "max": 18})
        self.assertEqual(report["metrics"]["ii"], 16)
        self.assertEqual(report["metrics"]["resources"], {"lut": 103, "ff": 12, "bram": 0, "dsp": 0})

    def test_wrapper_files_do_not_contain_unreplaced_placeholders(self):
        forbidden = ["{top}", "{part}", "{period}"]
        wrapper_files = [
            WRAPPER_DIR / "run.tcl",
            WRAPPER_DIR / "run-hls-in-docker.sh",
            WRAPPER_DIR / "run-vector-add-in-docker.sh",
        ]

        for path in wrapper_files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
