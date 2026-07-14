from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent.main import (
    EXIT_BASELINE_CORRECTNESS_FAILURE,
    EXIT_INPUT_OR_CONFIG_ERROR,
    EXIT_SAFE_FALLBACK,
    EXIT_SUCCESS,
    main,
    parse_args,
    run_agent,
)
from agent.execution.result_adapter import UnifiedToolResult


TASK_ROOT = Path("fpt26-harness/tasks")
PROJECTION = TASK_ROOT / "projection_bugfix"
DOT_PRODUCT = TASK_ROOT / "dotProduct_optimize"
RESIDUAL = TASK_ROOT / "residual_stream_deadlock"


class FakeToolServer:
    def __init__(self, task, budget, run_root: Path) -> None:
        self.task = task
        self.budget = budget
        self.run_root = Path(run_root)
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.transcript: list[SimpleNamespace] = []


class FakeBackend:
    instances: list["FakeBackend"] = []

    def __init__(self, task, tool_server) -> None:
        self.task = task
        self.tool_server = tool_server
        self.calls: list[str] = []
        self.kernel_inputs: list[str] = []
        FakeBackend.instances.append(self)

    def csim(self, kernel_code: str) -> UnifiedToolResult:
        if self.task.id == "projection_bugfix" and kernel_code == self.task.kernel_code:
            return self._result("csim", "runtime_fail", "Mismatch at angle 0: expected average z including z2\n")
        return self._result("csim", "pass", "C simulation passed\n")

    def synth(self, kernel_code: str) -> UnifiedToolResult:
        if self.task.id == "dotProduct_optimize" and "#pragma HLS PIPELINE" in kernel_code:
            metrics = _metrics(latency=20, ii=1, clock=4.1, lut=130)
        elif self.task.id == "dotProduct_optimize":
            metrics = _metrics(latency=120, ii=8, clock=4.3, lut=100)
        else:
            metrics = _metrics(latency=40, ii=1, clock=4.2, lut=90)
        return self._result("synth", "pass", "Synthesis passed\n", metrics=metrics)

    def cosim(self, kernel_code: str) -> UnifiedToolResult:
        if self.task.id == "residual_stream_deadlock" and kernel_code == self.task.kernel_code:
            return self._result(
                "cosim",
                "cosim_fail",
                "// ERROR!!! DEADLOCK DETECTED\n"
                "// Blocked by full output FIFO 'residual.s_main_U'\n"
                "// Blocked by empty input FIFO 'residual.s_skip_U'\n",
            )
        return self._result("cosim", "pass", "Co-simulation passed\n")

    def _result(
        self,
        stage: str,
        status: str,
        log_text: str,
        *,
        metrics: dict | None = None,
    ) -> UnifiedToolResult:
        self.calls.append(stage)
        kernel_code = self.kernel_inputs[-1] if False and self.kernel_inputs else ""
        del kernel_code
        before = self.tool_server.budget.spent
        self.tool_server.budget.charge(stage)
        after = self.tool_server.budget.spent
        self.tool_server.transcript.append(
            SimpleNamespace(
                n=len(self.tool_server.transcript) + 1,
                kind=stage,
                phase=status,
                spent=after,
                detail=f"[{stage}] {status}",
            )
        )
        run_dir = self.tool_server.run_root / f"{stage}_{len(self.calls)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "tool.log"
        log_path.write_text(log_text, encoding="utf-8")
        artifacts = {"run_dir": str(run_dir), "tool_log": str(log_path)}
        if stage == "cosim":
            report_dir = run_dir / "report"
            report_dir.mkdir(parents=True, exist_ok=True)
            artifacts["cosim_report_dir"] = str(report_dir)
        return UnifiedToolResult(
            stage=stage,
            status=status,
            return_code=0 if status == "pass" else 1,
            elapsed_seconds=0.1,
            summary=f"[{stage}] {status}",
            metrics=metrics or {},
            artifacts=artifacts,
            budget_before=before,
            budget_after=after,
        )


def _metrics(*, latency: int, ii: int, clock: float, lut: int) -> dict:
    return {
        "estimated_clock_ns": clock,
        "latency_min": latency,
        "latency_max": latency,
        "ii_min": ii,
        "ii_max": ii,
        "lut": lut,
        "ff": 50,
        "dsp": 0,
        "bram": 0,
        "uram": 0,
    }


class FakeLLMHandler(BaseHTTPRequestHandler):
    responses: list[dict] = []
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.__class__.requests.append(
            {
                "headers": {key: value for key, value in self.headers.items()},
                "body": json.loads(body),
            }
        )
        payload = self.__class__.responses.pop(0)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, fmt, *args):
        return


class FakeLLMServer:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self):
        FakeLLMHandler.responses = list(self.responses)
        FakeLLMHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLMHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        assert self.server is not None
        self.server.shutdown()
        self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        assert self.server is not None
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    @property
    def request_count(self) -> int:
        return len(FakeLLMHandler.requests)


def _chat_payload(content: dict, *, tokens: int = 33) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {
            "prompt_tokens": tokens,
            "completion_tokens": tokens + 1,
            "total_tokens": tokens * 2 + 1,
        },
    }


def _repair_payload(kernel: str) -> dict:
    return _chat_payload(
        {
            "diagnosis": "missing z2 contribution",
            "replacement_kernel": kernel,
            "changes": ["include z2 in the angle 0 z average"],
            "confidence": "high",
        }
    )


def _structural_payload(kernel: str) -> dict:
    return _chat_payload(
        {
            "diagnosis": "producer writes streams in isolated bursts",
            "repair_strategy": "pair writes in one loop",
            "affected_streams": ["s_main", "s_skip"],
            "replacement_kernel": kernel,
            "changes": ["combine stageA stream writes"],
            "confidence": "high",
        },
        tokens=44,
    )


def _llm_env(base_url: str, *, api_key: str = "secret-cli-key") -> dict[str, str]:
    return {
        "FPT26_LLM_BASE_URL": base_url,
        "FPT26_LLM_MODEL": "fake-open-cli-model",
        "FPT26_LLM_MODEL_VERSION": "test",
        "FPT26_LLM_API_KEY": api_key,
        "FPT26_LLM_TIMEOUT_SECONDS": "5",
        "FPT26_LLM_MAX_OUTPUT_TOKENS": "8192",
        "FPT26_LLM_TEMPERATURE": "0",
        "FPT26_LLM_LICENSE": "Apache-2.0",
        "FPT26_LLM_SOURCE": "local-fake-http",
        "FPT26_LLM_MAX_RETRIES": "0",
    }


def _run_cli(
    task: Path,
    mode: str,
    output_root: Path,
    *,
    env: dict[str, str] | None = None,
    summary_format: str = "json",
    **kwargs,
) -> tuple[int, dict, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    FakeBackend.instances = []
    with mock.patch.dict(os.environ, env or {}, clear=False):
        code = run_agent(
            task_path=task,
            mode=mode,
            output_root=output_root,
            summary_format=summary_format,
            tool_server_factory=FakeToolServer,
            backend_factory=FakeBackend,
            stdout=stdout,
            stderr=stderr,
            **kwargs,
        )
    text = stdout.getvalue().strip()
    return code, json.loads(text) if text else {}, stderr.getvalue()


class AgentCliTests(unittest.TestCase):
    def test_parse_args_accepts_official_task_cli(self):
        args = parse_args(["--task", str(PROJECTION), "--mode", "repair", "--output-root", "runs/cli"])
        self.assertEqual(args.task, PROJECTION)
        self.assertEqual(args.mode, "repair")
        self.assertEqual(args.output_root, Path("runs/cli"))

    def test_missing_task_and_invalid_mode_return_2(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            stdout = io.StringIO()
            stderr = io.StringIO()
            missing = run_agent(
                task_path=Path(tmp_name) / "missing",
                mode="baseline",
                output_root=Path(tmp_name) / "runs",
                stdout=stdout,
                stderr=stderr,
            )
            with contextlib.redirect_stderr(io.StringIO()):
                invalid = main(["--task", str(PROJECTION), "--mode", "bad"])

        self.assertEqual(missing, EXIT_INPUT_OR_CONFIG_ERROR)
        self.assertEqual(invalid, EXIT_INPUT_OR_CONFIG_ERROR)

    def test_baseline_mode_does_not_load_llm(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            FakeBackend.instances = []

            def no_llm():
                raise AssertionError("LLM must not be loaded for baseline")

            stdout = io.StringIO()
            code = run_agent(
                task_path=DOT_PRODUCT,
                mode="baseline",
                output_root=tmp / "runs",
                tool_server_factory=FakeToolServer,
                backend_factory=FakeBackend,
                llm_client_factory=no_llm,
                stdout=stdout,
                stderr=io.StringIO(),
            )
            summary = json.loads(stdout.getvalue())

        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(summary["mode"], "baseline")
        self.assertEqual(summary["stage_statuses"][0]["stage"], "csim")
        self.assertEqual(FakeBackend.instances[0].calls, ["csim", "synth"])

    def test_repair_mode_missing_llm_config_fails_before_tools(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            stdout = io.StringIO()
            stderr = io.StringIO()
            FakeBackend.instances = []
            with mock.patch.dict(os.environ, {}, clear=True):
                code = run_agent(
                    task_path=PROJECTION,
                    mode="repair",
                    output_root=tmp / "runs",
                    tool_server_factory=FakeToolServer,
                    backend_factory=FakeBackend,
                    stdout=stdout,
                    stderr=stderr,
                )

        self.assertEqual(code, EXIT_INPUT_OR_CONFIG_ERROR)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(FakeBackend.instances, [])
        self.assertIn("FPT26_LLM_BASE_URL", stderr.getvalue())

    def test_projection_repair_cli_with_fake_api(self):
        fixed = (PROJECTION / "reference" / "projection.cpp").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp_name, FakeLLMServer([_repair_payload(fixed)]) as server:
            tmp = Path(tmp_name)
            code, summary, stderr = _run_cli(
                PROJECTION,
                "repair",
                tmp / "runs",
                env=_llm_env(server.base_url),
                max_repair_attempts=1,
            )
            run_dir = Path(summary["run_directory"])
            final_kernel = (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8")

        self.assertEqual(code, EXIT_SUCCESS, stderr)
        self.assertEqual(server.request_count, 1)
        self.assertEqual(summary["task_id"], "projection_bugfix")
        self.assertEqual(summary["repair_status"], "repaired")
        self.assertEqual(summary["selected_candidate_id"], "c001_repair_llm_01")
        self.assertEqual([item["status"] for item in summary["stage_statuses"]], ["runtime_fail", "pass", "pass"])
        self.assertEqual(final_kernel, fixed)

    def test_dot_product_optimize_cli_uses_only_optimization(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            FakeBackend.instances = []

            def no_llm():
                raise AssertionError("LLM must not be loaded for optimize")

            stdout = io.StringIO()
            code = run_agent(
                task_path=DOT_PRODUCT,
                mode="optimize",
                output_root=tmp / "runs",
                tool_server_factory=FakeToolServer,
                backend_factory=FakeBackend,
                llm_client_factory=no_llm,
                max_optimization_candidates=1,
                stdout=stdout,
                stderr=io.StringIO(),
            )
            summary = json.loads(stdout.getvalue())
            run_dir = Path(summary["run_directory"])
            final_kernel = (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8")
            selected_kernel = (run_dir / "candidates" / "c001_pipeline_01" / "kernel.cpp").read_text(encoding="utf-8")

        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(summary["optimization_status"], "improved")
        self.assertEqual(summary["repair_status"], "not_attempted")
        self.assertEqual(summary["structural_repair_status"], "not_attempted")
        self.assertEqual(summary["selected_candidate_id"], "c001_pipeline_01")
        self.assertEqual(final_kernel, selected_kernel)

    def test_residual_structural_cli_with_fake_api(self):
        fixed = (RESIDUAL / "reference" / "residual.cpp").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp_name, FakeLLMServer([_structural_payload(fixed)]) as server:
            tmp = Path(tmp_name)
            code, summary, stderr = _run_cli(
                RESIDUAL,
                "structural",
                tmp / "runs",
                env=_llm_env(server.base_url),
                max_structural_repair_attempts=1,
            )
            run_dir = Path(summary["run_directory"])
            final_kernel = (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8")

        self.assertEqual(code, EXIT_SUCCESS, stderr)
        self.assertEqual(server.request_count, 1)
        self.assertEqual(summary["structural_repair_status"], "repaired")
        self.assertEqual(summary["selected_candidate_id"], "c001_structural_llm_01")
        self.assertEqual([item["stage"] for item in summary["stage_statuses"]], ["csim", "synth", "cosim", "csim", "synth", "cosim"])
        self.assertEqual(final_kernel, fixed)

    def test_baseline_failure_exit_code_is_3_and_repair_failure_is_safe_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            baseline_code, baseline_summary, _stderr = _run_cli(PROJECTION, "baseline", tmp / "baseline")
        with tempfile.TemporaryDirectory() as tmp_name, FakeLLMServer([_repair_payload((PROJECTION / "projection.cpp").read_text(encoding="utf-8"))]) as server:
            tmp = Path(tmp_name)
            repair_code, repair_summary, _stderr = _run_cli(
                PROJECTION,
                "repair",
                tmp / "repair",
                env=_llm_env(server.base_url),
                max_repair_attempts=1,
            )

        self.assertEqual(baseline_code, EXIT_BASELINE_CORRECTNESS_FAILURE)
        self.assertEqual(baseline_summary["status"], "stopped")
        self.assertEqual(repair_code, EXIT_SAFE_FALLBACK)
        self.assertEqual(repair_summary["status"], "repair_failed")

    def test_api_key_is_redacted_from_stdout_stderr_and_manifest(self):
        secret = "super-secret-cli-token"
        fixed = (PROJECTION / "reference" / "projection.cpp").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp_name, FakeLLMServer([_repair_payload(fixed)]) as server:
            tmp = Path(tmp_name)
            code, summary, stderr = _run_cli(
                PROJECTION,
                "repair",
                tmp / "runs",
                env=_llm_env(server.base_url, api_key=secret),
                max_repair_attempts=1,
            )
            run_dir = Path(summary["run_directory"])
            manifest_text = (run_dir / "run_manifest.json").read_text(encoding="utf-8")
            llm_text = (run_dir / "llm" / "calls.jsonl").read_text(encoding="utf-8")

        self.assertEqual(code, EXIT_SUCCESS, stderr)
        self.assertNotIn(secret, json.dumps(summary))
        self.assertNotIn(secret, stderr)
        self.assertNotIn(secret, manifest_text)
        self.assertNotIn(secret, llm_text)

    def test_run_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            first_code, first, _stderr = _run_cli(DOT_PRODUCT, "baseline", tmp / "runs")
            second_code, second, _stderr2 = _run_cli(DOT_PRODUCT, "baseline", tmp / "runs")

        self.assertEqual(first_code, EXIT_SUCCESS)
        self.assertEqual(second_code, EXIT_SUCCESS)
        self.assertNotEqual(first["run_directory"], second["run_directory"])
        self.assertTrue(first["run_directory"].endswith("run_000"))
        self.assertTrue(second["run_directory"].endswith("run_001"))

    def test_zip_and_unzip_are_available_in_container(self):
        self.assertIsNotNone(shutil.which("zip"))
        self.assertIsNotNone(shutil.which("unzip"))

    def test_text_summary_uses_official_style_sections_without_prompt_or_kernel(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            stdout = io.StringIO()
            code = run_agent(
                task_path=DOT_PRODUCT,
                mode="baseline",
                output_root=tmp / "runs",
                summary_format="text",
                tool_server_factory=FakeToolServer,
                backend_factory=FakeBackend,
                stdout=stdout,
                stderr=io.StringIO(),
            )
            text = stdout.getvalue()

        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("=== Task dotProduct_optimize [optimize] ===", text)
        self.assertIn("--- metered tool transcript ---", text)
        self.assertIn("--- agent result ---", text)
        self.assertIn("--- stage results ---", text)
        self.assertIn("#1", text)
        self.assertIn("budget 5/40 credits spent", text)
        self.assertNotIn("#include", text)
        self.assertNotIn("messages", text)


if __name__ == "__main__":
    unittest.main()
