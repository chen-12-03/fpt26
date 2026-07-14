import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.main import run_agent
from agent.natural_language_flow import NaturalLanguageRunResult


AGENT_ROOT = Path(__file__).resolve().parents[1]
VALID_IR_FIXTURE = AGENT_ROOT / "tests" / "fixtures" / "vector_add_existing_code_ir.json"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _load_fixture() -> dict:
    return json.loads(VALID_IR_FIXTURE.read_text(encoding="utf-8"))


class AgentMainTests(unittest.TestCase):
    def write_ir(self, data: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ir.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def write_fake_runner(self, *, write_manifest: bool = False) -> tuple[Path, Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp_path = Path(tmp.name)
        capture_path = tmp_path / "capture.json"
        run_dir = tmp_path / "runs" / "vector_add" / "replay_000"
        runner_path = tmp_path / "fake-runner.py"
        if write_manifest:
            text = f"""#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["CAPTURE_PATH"], "w", encoding="utf-8") as f:
    json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd()}}, f)

run_dir = {str(run_dir)!r}
os.makedirs(run_dir, exist_ok=True)
with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump({{"task_id": "vector_add"}}, f)
print("wrapper: run_dir=" + run_dir)
sys.exit(0)
"""
        else:
            text = """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["CAPTURE_PATH"], "w", encoding="utf-8") as f:
    json.dump({"argv": sys.argv[1:], "cwd": os.getcwd()}, f)

sys.exit(0)
"""
        _write_executable(runner_path, text)
        return runner_path, capture_path, run_dir

    def test_ir_baseline_delegates_to_existing_code_entrypoint(self):
        runner_path, capture_path, _ = self.write_fake_runner()

        with mock.patch.dict(os.environ, {"CAPTURE_PATH": str(capture_path)}):
            exit_code = run_agent(
                VALID_IR_FIXTURE,
                input_type="ir",
                mode="baseline",
                runner_path=runner_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        capture = json.loads(capture_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(capture["cwd"], str(AGENT_ROOT))
        self.assertIn("--task-id", capture["argv"])
        self.assertIn("vector_add", capture["argv"])
        self.assertIn("--candidate-prefix", capture["argv"])
        self.assertIn("baseline", capture["argv"])
        self.assertIn("--source", capture["argv"])
        self.assertIn("benchmarks/public/vector_add/kernel.cpp", capture["argv"])

    def test_ir_replay_delegates_and_records_manifest_metadata(self):
        runner_path, capture_path, run_dir = self.write_fake_runner(write_manifest=True)

        with mock.patch.dict(os.environ, {"CAPTURE_PATH": str(capture_path)}):
            exit_code = run_agent(
                VALID_IR_FIXTURE,
                input_type="ir",
                mode="replay",
                runner_path=runner_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("--candidate-prefix", capture["argv"])
        self.assertIn("replay", capture["argv"])
        self.assertEqual(manifest["mode"], "replay")
        self.assertEqual(manifest["input_type"], "ir")
        self.assertEqual(Path(manifest["input_ir"]), VALID_IR_FIXTURE.resolve())
        self.assertEqual(manifest["input_ir_source_file"], "benchmarks/public/vector_add/kernel.cpp")
        self.assertEqual(manifest["input_ir_testbench_file"], "benchmarks/public/vector_add/host.cpp")
        self.assertEqual(manifest["llm"], {"called": False})

    def test_natural_language_baseline_delegates_to_flow(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp_path = Path(tmp.name)
        spec_path = tmp_path / "spec.txt"
        spec_path.write_text("Create vector_add.", encoding="utf-8")
        runner_path, _, _ = self.write_fake_runner()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch(
            "agent.main.run_natural_language_baseline",
            return_value=NaturalLanguageRunResult(
                exit_code=0,
                work_dir=tmp_path / "agent_runs" / "baseline_000",
                final_run_dir=tmp_path / "runs" / "vector_add" / "baseline_000",
            ),
        ) as run_flow:
            exit_code = run_agent(
                spec_path,
                input_type="natural-language",
                mode="baseline",
                runner_path=runner_path,
                agent_work_root=tmp_path / "agent_runs",
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(exit_code, 0)
        run_flow.assert_called_once_with(
            spec_path,
            runner_path=runner_path,
            work_root=tmp_path / "agent_runs",
            stdout=stdout,
            stderr=stderr,
        )

    def test_natural_language_replay_fails_before_flow(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        spec_path = Path(tmp.name) / "spec.txt"
        spec_path.write_text("Create vector_add.", encoding="utf-8")
        runner_path, _, _ = self.write_fake_runner()

        with mock.patch("agent.main.run_natural_language_baseline") as run_flow:
            exit_code = run_agent(
                spec_path,
                input_type="natural-language",
                mode="replay",
                runner_path=runner_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 2)
        run_flow.assert_not_called()

    def test_unsupported_input_type_fails_before_runner_starts(self):
        runner_path, capture_path, _ = self.write_fake_runner()

        with mock.patch.dict(os.environ, {"CAPTURE_PATH": str(capture_path)}):
            exit_code = run_agent(
                VALID_IR_FIXTURE,
                input_type="natural_language",
                mode="baseline",
                runner_path=runner_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 2)
        self.assertFalse(capture_path.exists())

    def test_unsupported_mode_fails_before_runner_starts(self):
        runner_path, capture_path, _ = self.write_fake_runner()

        with mock.patch.dict(os.environ, {"CAPTURE_PATH": str(capture_path)}):
            exit_code = run_agent(
                VALID_IR_FIXTURE,
                input_type="ir",
                mode="search",
                runner_path=runner_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 2)
        self.assertFalse(capture_path.exists())

    def test_invalid_ir_fails_before_runner_starts(self):
        data = _load_fixture()
        data["top_function"] = ""
        ir_path = self.write_ir(data)
        runner_path, capture_path, _ = self.write_fake_runner(write_manifest=True)

        with mock.patch.dict(os.environ, {"CAPTURE_PATH": str(capture_path)}):
            exit_code = run_agent(
                ir_path,
                input_type="ir",
                mode="replay",
                runner_path=runner_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 2)
        self.assertFalse(capture_path.exists())


if __name__ == "__main__":
    unittest.main()
