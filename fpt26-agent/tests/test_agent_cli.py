from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent.config import (
    DEFAULT_MAX_OPTIMIZATION_CANDIDATES,
    DEFAULT_MAX_REPAIR_ATTEMPTS,
    DEFAULT_MAX_STRUCTURAL_REPAIR_ATTEMPTS,
    OFFICIAL_REFERENCE_MAX_ROUNDS,
    config_from_args,
)
from agent.main import (
    EXIT_BASELINE_CORRECTNESS_FAILURE,
    EXIT_INPUT_OR_CONFIG_ERROR,
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


def _optimization_payload(kernel: str) -> dict:
    return _chat_payload(
        {
            "diagnosis": "sequential dot product loop has high latency",
            "optimization_strategy": "partition arrays and pipeline the reduction loop",
            "replacement_kernel": kernel,
            "changes": ["add array partition pragmas", "pipeline the tiled loop"],
            "expected_latency_impact": "lower latency through parallel memory access and II=1 pipeline",
            "confidence": "high",
        },
        tokens=55,
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


@dataclass
class FakeScorecard:
    task_id: str
    difficulty: int
    functional_pass: bool
    synth_pass: bool
    cosim_pass: bool | None
    baseline_latency: int | None
    candidate_latency: int | None
    acceleration: float | None
    is_opt: bool
    score: float
    baseline_report: dict
    candidate_report: dict

    def render(self) -> str:
        return (
            f"=== Scorecard: {self.task_id} (difficulty {self.difficulty}) ===\n"
            f"  functional (hidden TB): {'PASS' if self.functional_pass else 'FAIL'}\n"
            f"  synthesizable         : {'PASS' if self.synth_pass else 'FAIL'}\n"
            f"  SCORE                 : {self.score:.3f}"
        )


def fake_scorer(task, candidate_kernel: str, work_root: Path) -> FakeScorecard:
    work_root.mkdir(parents=True, exist_ok=True)
    (work_root / "fake_grade.log").write_text("fake official grade\n", encoding="utf-8")
    return FakeScorecard(
        task_id=task.id,
        difficulty=task.difficulty,
        functional_pass="dotProduct" in candidate_kernel,
        synth_pass=True,
        cosim_pass=None,
        baseline_latency=120,
        candidate_latency=80,
        acceleration=1.5,
        is_opt=True,
        score=2.345,
        baseline_report={
            "clock_period_ns": 4.3,
            "latency_best": 120,
            "latency_avg": 120,
            "latency_worst": 120,
            "interval_min": 8,
            "interval_max": 8,
            "resources": {
                "LUT": 100,
                "FF": 50,
                "DSP": 0,
                "BRAM_18K": 0,
                "URAM": 0,
            },
            "available": {},
            "utilization": {},
        },
        candidate_report={
            "clock_period_ns": 4.0,
            "latency_best": 80,
            "latency_avg": 80,
            "latency_worst": 80,
            "interval_min": 1,
            "interval_max": 1,
            "resources": {
                "LUT": 111,
                "FF": 55,
                "DSP": 0,
                "BRAM_18K": 0,
                "URAM": 0,
            },
            "available": {},
            "utilization": {},
        },
    )


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

    def test_default_agent_round_limits_match_official_reference_agent(self):
        args = parse_args(["--task", str(PROJECTION), "--mode", "repair"])
        config = config_from_args(args, env={})

        self.assertEqual(OFFICIAL_REFERENCE_MAX_ROUNDS, 6)
        self.assertEqual(DEFAULT_MAX_REPAIR_ATTEMPTS, OFFICIAL_REFERENCE_MAX_ROUNDS)
        self.assertEqual(DEFAULT_MAX_STRUCTURAL_REPAIR_ATTEMPTS, OFFICIAL_REFERENCE_MAX_ROUNDS)
        self.assertEqual(DEFAULT_MAX_OPTIMIZATION_CANDIDATES, OFFICIAL_REFERENCE_MAX_ROUNDS)
        self.assertEqual(config.max_repair_attempts, OFFICIAL_REFERENCE_MAX_ROUNDS)
        self.assertEqual(config.max_structural_repair_attempts, OFFICIAL_REFERENCE_MAX_ROUNDS)
        self.assertEqual(config.max_optimization_candidates, OFFICIAL_REFERENCE_MAX_ROUNDS)

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
        self.assertIn("OPENROUTER_API_KEY", stderr.getvalue())

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
        self.assertEqual(server.request_count, 0)
        self.assertEqual(summary["task_id"], "projection_bugfix")
        self.assertEqual(summary["repair_status"], "repaired")
        self.assertEqual(summary["selected_candidate_id"], "c001_repair_deterministic_01")
        self.assertEqual([item["status"] for item in summary["stage_statuses"]], ["runtime_fail", "pass", "pass"])
        self.assertIn("triangle_3d.z2 / 3", final_kernel)

    def test_dot_product_full_cli_calls_llm_for_optimization(self):
        optimized = (DOT_PRODUCT / "reference" / "dotProduct.cpp").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp_name, FakeLLMServer([_optimization_payload(optimized)]) as server:
            tmp = Path(tmp_name)
            code, summary, stderr = _run_cli(
                DOT_PRODUCT,
                "full",
                tmp / "runs",
                env=_llm_env(server.base_url),
                max_optimization_candidates=1,
            )
            run_dir = Path(summary["run_directory"])
            final_kernel = (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8")
            selected_kernel = (run_dir / "candidates" / "c001_opt_llm_01" / "kernel.cpp").read_text(encoding="utf-8")
            llm_calls = (run_dir / "llm" / "calls.jsonl").read_text(encoding="utf-8")

        self.assertEqual(code, EXIT_SUCCESS, stderr)
        self.assertEqual(server.request_count, 1)
        self.assertEqual(summary["optimization_status"], "improved")
        self.assertEqual(summary["repair_status"], "not_attempted")
        self.assertEqual(summary["structural_repair_status"], "not_attempted")
        self.assertEqual(summary["selected_candidate_id"], "c001_opt_llm_01")
        self.assertEqual(summary["llm_usage"]["attempt_count"], 1)
        self.assertEqual(summary["llm_usage"]["total_tokens"], 111)
        self.assertIn('"purpose": "optimization"', llm_calls)
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

    def test_baseline_failure_exit_code_is_3_and_deterministic_repair_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            baseline_code, baseline_summary, _stderr = _run_cli(PROJECTION, "baseline", tmp / "baseline")
            baseline_report = json.loads(Path(baseline_summary["report"]["report_json"]).read_text(encoding="utf-8"))
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
        self.assertEqual(baseline_report["workflow"]["controllers"]["repair"]["state"], "disabled")
        self.assertEqual(baseline_report["workflow"]["controllers"]["repair"]["reason"], "disabled_by_mode")
        self.assertEqual(server.request_count, 0)
        self.assertEqual(repair_code, EXIT_SUCCESS)
        self.assertEqual(repair_summary["status"], "completed")
        self.assertEqual(repair_summary["selected_candidate_id"], "c001_repair_deterministic_01")
        self.assertEqual([item["status"] for item in repair_summary["stage_statuses"]], ["runtime_fail", "pass", "pass"])
        self.assertEqual(repair_summary["report"]["workflow"]["controllers"]["repair"]["state"], "attempted")

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
        self.assertIn("--- experimental report ---", text)
        self.assertIn("#1", text)
        self.assertIn("budget 5/40 credits spent", text)
        self.assertNotIn("#include", text)
        self.assertNotIn("messages", text)

    def test_report_is_persisted_for_normal_run(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            code, summary, stderr = _run_cli(DOT_PRODUCT, "baseline", tmp / "runs")
            run_dir = Path(summary["run_directory"])
            report_json = Path(summary["report"]["report_json"])
            report_txt = Path(summary["report"]["report_txt"])
            report = json.loads(report_json.read_text(encoding="utf-8"))
            report_text = report_txt.read_text(encoding="utf-8")
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(code, EXIT_SUCCESS, stderr)
        self.assertEqual(report["schema_version"], "fpt26-agent-experimental-report-v1")
        self.assertEqual(report["task"]["task_id"], "dotProduct_optimize")
        self.assertEqual(report["verification"]["csim_status"], "pass")
        self.assertEqual(report["verification"]["synth_status"], "pass")
        self.assertEqual(report["workflow"]["controllers"]["optimization"]["reason"], "disabled_by_mode")
        self.assertEqual(report["ppa"]["latency_max"], 120)
        self.assertEqual(report["paths"]["run_directory"], str(run_dir))
        self.assertIn("Experimental Report", report_text)
        self.assertEqual(manifest["reporting"]["report"]["report_json"], str(report_json))
        self.assertIsNone(manifest["reporting"]["scoring"])

    def test_score_flag_persists_official_scorecard_and_adds_summary(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            stdout = io.StringIO()
            code = run_agent(
                task_path=DOT_PRODUCT,
                mode="baseline",
                output_root=tmp / "runs",
                score=True,
                scorer=fake_scorer,
                tool_server_factory=FakeToolServer,
                backend_factory=FakeBackend,
                stdout=stdout,
                stderr=io.StringIO(),
            )
            summary = json.loads(stdout.getvalue())
            run_dir = Path(summary["run_directory"])
            scorecard_json = run_dir / "scoring" / "scorecard.json"
            scorecard_txt = run_dir / "scoring" / "scorecard.txt"
            report_json = run_dir / "report" / "report.json"
            scorecard = json.loads(scorecard_json.read_text(encoding="utf-8"))
            scorecard_text = scorecard_txt.read_text(encoding="utf-8")
            report = json.loads(report_json.read_text(encoding="utf-8"))
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(summary["scoring"]["score"], 2.345)
        self.assertEqual(summary["report"]["ppa"]["latency_max"], 80)
        self.assertEqual(summary["report"]["ppa"]["lut"], 111)
        self.assertEqual(scorecard["task_id"], "dotProduct_optimize")
        self.assertEqual(scorecard["score"], 2.345)
        self.assertEqual(report["scoring"]["score"], 2.345)
        self.assertEqual(report["ppa"]["latency_max"], 80)
        self.assertEqual(report["ppa"]["lut"], 111)
        self.assertEqual(manifest["reporting"]["scoring"]["score"], 2.345)
        self.assertEqual(manifest["reporting"]["report"]["ppa"]["lut"], 111)
        self.assertIn("Scorecard", scorecard_text)

    def test_score_text_summary_contains_official_scorecard_section(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            stdout = io.StringIO()
            code = run_agent(
                task_path=DOT_PRODUCT,
                mode="baseline",
                output_root=tmp / "runs",
                score=True,
                scorer=fake_scorer,
                summary_format="text",
                tool_server_factory=FakeToolServer,
                backend_factory=FakeBackend,
                stdout=stdout,
                stderr=io.StringIO(),
            )
            text = stdout.getvalue()

        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("--- official scorecard (hidden grading, uncharged) ---", text)
        self.assertIn("functional (hidden TB): PASS", text)
        self.assertIn("SCORE", text)


if __name__ == "__main__":
    unittest.main()
