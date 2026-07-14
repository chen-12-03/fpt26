import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.run_existing_code import run_existing_code


AGENT_ROOT = Path(__file__).resolve().parents[1]
VALID_IR_FIXTURE = AGENT_ROOT / "tests" / "fixtures" / "vector_add_existing_code_ir.json"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _load_fixture() -> dict:
    return json.loads(VALID_IR_FIXTURE.read_text(encoding="utf-8"))


class RunExistingCodeTests(unittest.TestCase):
    def write_ir(self, data: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ir.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def write_fake_runner(self, exit_code: int = 0) -> tuple[Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp_path = Path(tmp.name)
        capture_path = tmp_path / "capture.json"
        runner_path = tmp_path / "fake-runner.py"
        _write_executable(
            runner_path,
            f"""#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["CAPTURE_PATH"], "w", encoding="utf-8") as f:
    json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd()}}, f)

print("fake runner stdout")
print("fake runner stderr", file=sys.stderr)
sys.exit({exit_code})
""",
        )
        return runner_path, capture_path

    def test_valid_ir_invokes_first_stage_runner_with_ir_fields(self):
        runner_path, capture_path = self.write_fake_runner()
        with mock.patch.dict(os.environ, {"CAPTURE_PATH": str(capture_path)}):
            exit_code = run_existing_code(
                VALID_IR_FIXTURE,
                runner_path=runner_path,
                candidate_prefix="existing_code",
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        capture = json.loads(capture_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(capture["cwd"], str(AGENT_ROOT))
        self.assertEqual(
            capture["argv"],
            [
                "--task-id",
                "vector_add",
                "--candidate-prefix",
                "existing_code",
                "--top",
                "vector_add",
                "--source",
                "benchmarks/public/vector_add/kernel.cpp",
                "--testbench",
                "benchmarks/public/vector_add/host.cpp",
                "--clock-period",
                "10.0",
                "--hls-part",
                "xcu55c-fsvh2892-2L-e",
            ],
        )

    def test_invalid_ir_fails_before_runner_starts(self):
        data = _load_fixture()
        data["clock_period_ns"] = -1
        ir_path = self.write_ir(data)
        runner_path, capture_path = self.write_fake_runner()

        with mock.patch.dict(os.environ, {"CAPTURE_PATH": str(capture_path)}):
            exit_code = run_existing_code(
                ir_path,
                runner_path=runner_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 2)
        self.assertFalse(capture_path.exists())

    def test_missing_source_fails_before_runner_starts(self):
        data = _load_fixture()
        data["source_file"] = "benchmarks/public/vector_add/does-not-exist.cpp"
        ir_path = self.write_ir(data)
        runner_path, capture_path = self.write_fake_runner()

        with mock.patch.dict(os.environ, {"CAPTURE_PATH": str(capture_path)}):
            exit_code = run_existing_code(
                ir_path,
                runner_path=runner_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 2)
        self.assertFalse(capture_path.exists())

    def test_runner_exit_code_is_returned(self):
        runner_path, capture_path = self.write_fake_runner(exit_code=17)

        with mock.patch.dict(os.environ, {"CAPTURE_PATH": str(capture_path)}):
            exit_code = run_existing_code(
                VALID_IR_FIXTURE,
                runner_path=runner_path,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(exit_code, 17)
        self.assertTrue(capture_path.exists())


if __name__ == "__main__":
    unittest.main()
