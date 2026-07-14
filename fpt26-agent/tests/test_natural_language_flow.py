import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.ir import SCHEMA_VERSION, load_ir
from agent.llm_client import LLMCallResult, LLMTimeoutError
from agent.natural_language_flow import run_natural_language_baseline


AGENT_ROOT = Path(__file__).resolve().parents[1]


def valid_natural_language_ir() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": "vector_add",
        "input_mode": "natural_language",
        "top_function": "vector_add",
        "source_file": None,
        "testbench_file": None,
        "inputs": [
            {"name": "a", "data_type": "int", "shape": [16]},
            {"name": "b", "data_type": "int", "shape": [16]},
        ],
        "outputs": [
            {"name": "c", "data_type": "int", "shape": [16]},
        ],
        "clock_period_ns": 10.0,
        "hls_part": "xcu55c-fsvh2892-2L-e",
        "verification": {
            "csim": {"enabled": True},
            "synth": {"enabled": True},
            "cosim": {"enabled": False},
        },
        "inferred_fields": {
            "operation": {"value": "vector_add", "source": "test"},
            "source_file": {"reason": "pending deterministic template generation"},
            "testbench_file": {"reason": "pending deterministic template generation"},
        },
    }


def llm_result(response_text: str, *, usage: bool = True) -> LLMCallResult:
    return LLMCallResult(
        model="open-source-model",
        response_text=response_text,
        input_tokens=17 if usage else None,
        output_tokens=19 if usage else None,
        total_tokens=36 if usage else None,
        elapsed_seconds=0.25,
        prompt_hash="b" * 64,
    )


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class NaturalLanguageFlowTests(unittest.TestCase):
    def make_tmpdir(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def write_spec(self, directory: Path) -> Path:
        spec_path = directory / "spec.txt"
        spec_path.write_text("Create vector_add for two int arrays of length 16.", encoding="utf-8")
        return spec_path

    def write_fake_runner(self, directory: Path, *, exit_code: int = 0) -> tuple[Path, Path, Path]:
        capture_path = directory / "capture.json"
        run_dir = directory / "runs" / "vector_add" / "baseline_000"
        runner_path = directory / "fake-runner.py"
        text = f"""#!/usr/bin/env python3
import json
import os
import sys

with open({str(capture_path)!r}, "w", encoding="utf-8") as f:
    json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd()}}, f)

run_dir = {str(run_dir)!r}
os.makedirs(run_dir, exist_ok=True)
with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump({{"task_id": "vector_add"}}, f)
with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as f:
    json.dump({{"csim": {{"status": "pass"}}, "synth": {{"status": "pass"}}}}, f)
print("wrapper: run_dir=" + run_dir)
print("fake hls stderr", file=sys.stderr)
sys.exit({exit_code})
"""
        _write_executable(runner_path, text)
        return runner_path, capture_path, run_dir

    def test_full_mock_chain_materializes_artifacts_and_invokes_runner(self):
        tmp = self.make_tmpdir()
        spec_path = self.write_spec(tmp)
        runner_path, capture_path, run_dir = self.write_fake_runner(tmp)
        work_root = tmp / "agent_runs"
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch(
            "agent.spec_extractor.call_chat_completion",
            return_value=llm_result(json.dumps(valid_natural_language_ir())),
        ):
            result = run_natural_language_baseline(
                spec_path,
                runner_path=runner_path,
                work_root=work_root,
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(result.exit_code, 0, stderr.getvalue())
        self.assertEqual(result.final_run_dir, run_dir)
        self.assertIsNotNone(result.work_dir)

        work_dir = result.work_dir
        assert work_dir is not None
        self.assertTrue((work_dir / "spec.txt").is_file())
        self.assertTrue((work_dir / "ir.json").is_file())
        self.assertTrue((work_dir / "llm_call.json").is_file())
        self.assertTrue((work_dir / "generated" / "kernel.cpp").is_file())
        self.assertTrue((work_dir / "generated" / "host.cpp").is_file())
        self.assertTrue((work_dir / "existing_code_ir.json").is_file())
        self.assertTrue((work_dir / "agent_manifest.json").is_file())
        self.assertTrue((work_dir / "hls.stdout.log").is_file())
        self.assertTrue((work_dir / "hls.stderr.log").is_file())

        natural_ir = load_ir(work_dir / "ir.json")
        derived_ir = load_ir(work_dir / "existing_code_ir.json")
        metadata = json.loads((work_dir / "llm_call.json").read_text(encoding="utf-8"))
        manifest = json.loads((work_dir / "agent_manifest.json").read_text(encoding="utf-8"))
        capture = json.loads(capture_path.read_text(encoding="utf-8"))

        self.assertEqual(natural_ir.input_mode, "natural_language")
        self.assertIsNone(natural_ir.source_file)
        self.assertIsNone(natural_ir.testbench_file)
        self.assertEqual(derived_ir.input_mode, "existing_code")
        self.assertEqual(Path(derived_ir.source_file), work_dir / "generated" / "kernel.cpp")
        self.assertEqual(Path(derived_ir.testbench_file), work_dir / "generated" / "host.cpp")
        self.assertEqual(derived_ir.inferred_fields["source_file"]["source"], "deterministic_vector_add_template")
        self.assertEqual(derived_ir.inferred_fields["testbench_file"]["source"], "deterministic_vector_add_template")
        self.assertEqual(derived_ir.inferred_fields["derived_from"]["input_mode"], "natural_language")
        self.assertEqual(metadata["model"], "open-source-model")
        self.assertEqual(metadata["prompt_hash"], "b" * 64)
        self.assertEqual(manifest["stages"]["spec_extraction"], "pass")
        self.assertEqual(manifest["stages"]["template_generation"], "pass")
        self.assertEqual(manifest["stages"]["derived_ir"], "pass")
        self.assertEqual(manifest["stages"]["hls"], "pass")
        self.assertEqual(Path(manifest["final_run_dir"]), run_dir)
        self.assertIn("wrapper: run_dir=", stdout.getvalue())
        self.assertIn("fake hls stderr", stderr.getvalue())

        self.assertEqual(capture["cwd"], str(AGENT_ROOT))
        self.assertEqual(
            capture["argv"],
            [
                "--task-id",
                "vector_add",
                "--candidate-prefix",
                "baseline",
                "--top",
                "vector_add",
                "--source",
                str(work_dir / "generated" / "kernel.cpp"),
                "--testbench",
                str(work_dir / "generated" / "host.cpp"),
                "--clock-period",
                "10.0",
                "--hls-part",
                "xcu55c-fsvh2892-2L-e",
            ],
        )

        runner_manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(runner_manifest["mode"], "baseline")
        self.assertEqual(runner_manifest["input_type"], "natural-language")
        self.assertEqual(runner_manifest["llm"], {"called": True})
        self.assertEqual(Path(runner_manifest["agent"]["agent_work_dir"]), work_dir)
        self.assertEqual(Path(runner_manifest["agent"]["natural_language_ir"]), work_dir / "ir.json")
        self.assertEqual(Path(runner_manifest["agent"]["derived_existing_code_ir"]), work_dir / "existing_code_ir.json")

    def test_llm_failure_stops_before_runner(self):
        tmp = self.make_tmpdir()
        spec_path = self.write_spec(tmp)
        runner_path, capture_path, _ = self.write_fake_runner(tmp)

        with mock.patch(
            "agent.spec_extractor.call_chat_completion",
            side_effect=LLMTimeoutError("LLM request timed out after 1 seconds"),
        ):
            result = run_natural_language_baseline(
                spec_path,
                runner_path=runner_path,
                work_root=tmp / "agent_runs",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(result.exit_code, 2)
        self.assertFalse(capture_path.exists())
        self.assertIsNotNone(result.work_dir)
        assert result.work_dir is not None
        manifest = json.loads((result.work_dir / "agent_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["stages"]["spec_extraction"], "fail")
        self.assertEqual(manifest["stages"]["hls"], "not_run")

    def test_template_failure_stops_before_runner(self):
        tmp = self.make_tmpdir()
        spec_path = self.write_spec(tmp)
        runner_path, capture_path, _ = self.write_fake_runner(tmp)
        data = valid_natural_language_ir()
        data["inferred_fields"]["operation"]["value"] = "matmul"

        with mock.patch(
            "agent.spec_extractor.call_chat_completion",
            return_value=llm_result(json.dumps(data)),
        ):
            result = run_natural_language_baseline(
                spec_path,
                runner_path=runner_path,
                work_root=tmp / "agent_runs",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(result.exit_code, 2)
        self.assertFalse(capture_path.exists())
        self.assertIsNotNone(result.work_dir)
        assert result.work_dir is not None
        manifest = json.loads((result.work_dir / "agent_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["stages"]["spec_extraction"], "pass")
        self.assertEqual(manifest["stages"]["template_generation"], "fail")
        self.assertEqual(manifest["stages"]["hls"], "not_run")

    def test_runner_exit_code_is_returned_and_logged(self):
        tmp = self.make_tmpdir()
        spec_path = self.write_spec(tmp)
        runner_path, capture_path, _ = self.write_fake_runner(tmp, exit_code=17)

        with mock.patch(
            "agent.spec_extractor.call_chat_completion",
            return_value=llm_result(json.dumps(valid_natural_language_ir()), usage=False),
        ):
            result = run_natural_language_baseline(
                spec_path,
                runner_path=runner_path,
                work_root=tmp / "agent_runs",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(result.exit_code, 17)
        self.assertTrue(capture_path.exists())
        self.assertIsNotNone(result.work_dir)
        assert result.work_dir is not None
        metadata = json.loads((result.work_dir / "llm_call.json").read_text(encoding="utf-8"))
        manifest = json.loads((result.work_dir / "agent_manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(metadata["input_tokens"])
        self.assertIsNone(metadata["output_tokens"])
        self.assertIsNone(metadata["total_tokens"])
        self.assertEqual(manifest["stages"]["hls"], "fail")
        self.assertEqual(manifest["final_exit_code"], 17)


if __name__ == "__main__":
    unittest.main()
