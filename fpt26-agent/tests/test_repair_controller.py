from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from agent.competition_agent import CompetitionAgent
from agent.execution.result_adapter import UnifiedToolResult
from agent.llm.config import LLMConfig
from agent.llm.llm_client import LLMClient
from agent.llm.schemas import LLMCallRecord, LLMResponse, prompt_sha256
from agent.llm.token_tracker import TokenTracker


PART = "xcu55c-fsvh2892-2L-e"
BASELINE_KERNEL = '#include "kernel.h"\nvoid top(int a, int *b) { *b = a - 1; }\n'
FIXED_KERNEL = '#include "kernel.h"\nvoid top(int a, int *b) { *b = a + 1; } // FIX\n'
BAD_KERNEL = '#include "kernel.h"\nvoid top(int a, int *b) { *b = a - 2; }\n'
SIGNATURE_CHANGED_KERNEL = '#include "kernel.h"\nvoid top(int a, int *b, int c) { *b = a + c; }\n'
PROJECTION_BUG_KERNEL = """#include "projection.h"

void projection(Triangle_3D triangle_3d, Triangle_2D *triangle_2d, bit2 angle) {
    if (angle == 0) {
        triangle_2d->z = triangle_3d.z0 / 3 + triangle_3d.z1 / 3;
    }
}
"""


class FakeBudget:
    def __init__(self, total: int = 20) -> None:
        self.total = total
        self.spent = 0
        self.cost = {"csim": 1, "synth": 4, "cosim": 20}
        self.calls: list[SimpleNamespace] = []

    def remaining(self) -> int:
        return self.total - self.spent

    def charge(self, kind: str) -> None:
        cost = self.cost[kind]
        self.spent += cost
        self.calls.append(SimpleNamespace(kind=kind, cost=cost, spent_after=self.spent))


class FakeToolServer:
    def __init__(self, total_budget: int = 20) -> None:
        self.budget = FakeBudget(total_budget)
        self.transcript: list[SimpleNamespace] = []


class FakeBackend:
    def __init__(self, _task, tool_server, log_dir: Path) -> None:
        self.tool_server = tool_server
        self.log_dir = log_dir
        self.calls: list[str] = []
        self.kernel_inputs: list[str] = []

    def csim(self, kernel_code: str) -> UnifiedToolResult:
        self.calls.append("csim")
        self.kernel_inputs.append(kernel_code)
        if "FIX" in kernel_code or "triangle_3d.z2 / 3" in kernel_code:
            return self._result("csim", "pass", "PASS\n")
        return self._result("csim", "runtime_fail", "Mismatch at output: expected 2 actual 0\n")

    def synth(self, kernel_code: str) -> UnifiedToolResult:
        self.calls.append("synth")
        self.kernel_inputs.append(kernel_code)
        if "SYNTH_FAIL" in kernel_code:
            return self._result("synth", "synth_error", "ERROR: Synthesizability check failed\n")
        return self._result("synth", "pass", "synth pass\n")

    def cosim(self, kernel_code: str) -> UnifiedToolResult:
        self.calls.append("cosim")
        self.kernel_inputs.append(kernel_code)
        return self._result("cosim", "pass", "cosim pass\n")

    def _result(self, stage: str, status: str, log_text: str) -> UnifiedToolResult:
        if status != "budget_exceeded":
            self.tool_server.budget.charge(stage)
            self.tool_server.transcript.append(
                SimpleNamespace(
                    n=len(self.tool_server.transcript) + 1,
                    kind=stage,
                    phase=status,
                    spent=self.tool_server.budget.spent,
                    detail=f"[{stage}] {status}",
                )
            )
        path = self.log_dir / f"{stage}_{len(self.calls)}.log"
        path.write_text(log_text, encoding="utf-8")
        return UnifiedToolResult(
            stage=stage,
            status=status,
            return_code=0 if status == "pass" else 1,
            elapsed_seconds=0.1,
            summary=f"[{stage}] {status}",
            metrics={},
            artifacts={"tool_log": str(path)},
            budget_before=0,
            budget_after=self.tool_server.budget.spent,
        )


class FakeLLMClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.token_tracker = TokenTracker()

    def generate(self, messages, response_schema=None, purpose=None):
        self.calls.append({"messages": messages, "response_schema": response_schema, "purpose": purpose})
        response = self.responses.pop(0)
        for record in response.attempts:
            self.token_tracker.record(record)
        return response


def llm_ok(kernel: str, *, diagnosis: str = "fixed bug", confidence: str = "high") -> LLMResponse:
    parsed = {
        "diagnosis": diagnosis,
        "replacement_kernel": kernel,
        "changes": ["updated arithmetic"],
        "confidence": confidence,
    }
    content = json.dumps(parsed)
    prompt = "0" * 64
    record = LLMCallRecord(
        purpose="repair",
        model="fake-open-model",
        model_version="test",
        license="Apache-2.0",
        source="fake",
        prompt_sha256=prompt,
        attempt_index=1,
        status="ok",
        http_status=200,
        input_tokens=11,
        output_tokens=13,
        total_tokens=24,
        usage_source="api",
        elapsed_seconds=0.01,
        error_type=None,
        error_message=None,
    )
    return LLMResponse(
        status="ok",
        content=content,
        parsed=parsed,
        model="fake-open-model",
        purpose="repair",
        prompt_sha256=prompt,
        input_tokens=11,
        output_tokens=13,
        total_tokens=24,
        usage_source="api",
        elapsed_seconds=0.01,
        attempt_count=1,
        error_type=None,
        error_message=None,
        model_version="test",
        license="Apache-2.0",
        source="fake",
        attempts=[record],
    )


def llm_error(error_type: str, message: str, *, attempt_count: int = 1) -> LLMResponse:
    prompt = "1" * 64
    attempts = []
    if attempt_count:
        attempts.append(
            LLMCallRecord(
                purpose="repair",
                model="fake-open-model",
                model_version="test",
                license="Apache-2.0",
                source="fake",
                prompt_sha256=prompt,
                attempt_index=1,
                status="error",
                http_status=None,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                usage_source="missing",
                elapsed_seconds=0.01,
                error_type=error_type,
                error_message=message,
            )
        )
    return LLMResponse(
        status="error",
        content=None,
        parsed=None,
        model="fake-open-model",
        purpose="repair",
        prompt_sha256=prompt,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        usage_source="missing",
        elapsed_seconds=0.01,
        attempt_count=attempt_count,
        error_type=error_type,
        error_message=message,
        model_version="test",
        license="Apache-2.0",
        source="fake",
        attempts=attempts,
    )


def make_task(tmp: Path, *, task_type: str = "repair", kernel: str = BASELINE_KERNEL):
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "kernel.cpp").write_text(kernel, encoding="utf-8")
    (tmp / "kernel.h").write_text("void top(int a, int *b);\n", encoding="utf-8")
    (tmp / "tb.cpp").write_text("int main(){int b=0; top(1,&b); return b==2 ? 0 : 1;}\n", encoding="utf-8")
    return SimpleNamespace(
        dir=tmp,
        id="unit_repair",
        type=task_type,
        difficulty=1,
        top="top",
        budget=20,
        part=PART,
        clock_ns=5.0,
        requires_cosim=False,
        initial_condition="",
        description="Set *b to a + 1.",
        kernel_name="kernel.cpp",
        kernel_code=kernel,
        headers={"kernel.h": "void top(int a, int *b);\n"},
        public_tb_name="tb.cpp",
        public_tb_code="int main(){int b=0; top(1,&b); return b==2 ? 0 : 1;}\n",
    )


def make_projection_task(tmp: Path):
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "projection.cpp").write_text(PROJECTION_BUG_KERNEL, encoding="utf-8")
    (tmp / "projection.h").write_text(
        "void projection(Triangle_3D triangle_3d, Triangle_2D *triangle_2d, bit2 angle);\n",
        encoding="utf-8",
    )
    (tmp / "projection_tb.cpp").write_text("int main(){return 1;}\n", encoding="utf-8")
    return SimpleNamespace(
        dir=tmp,
        id="projection_bugfix",
        type="repair",
        difficulty=1,
        top="projection",
        budget=20,
        part=PART,
        clock_ns=5.0,
        requires_cosim=False,
        initial_condition=(
            "C-simulation fails because the angle 0 branch drops z2 from the z average."
        ),
        description="For angle 0, z = z0/3 + z1/3 + z2/3.",
        kernel_name="projection.cpp",
        kernel_code=PROJECTION_BUG_KERNEL,
        headers={
            "projection.h": "void projection(Triangle_3D triangle_3d, Triangle_2D *triangle_2d, bit2 angle);\n"
        },
        public_tb_name="projection_tb.cpp",
        public_tb_code="int main(){return 1;}\n",
    )


class RepairControllerFakeTests(unittest.TestCase):
    def run_agent(
        self,
        tmp: Path,
        llm: FakeLLMClient,
        *,
        task_type: str = "repair",
        total_budget: int = 20,
        output_root: Path | None = None,
        max_attempts: int = 2,
    ):
        backends: list[FakeBackend] = []

        def factory(task, server):
            backend = FakeBackend(task, server, tmp)
            backends.append(backend)
            return backend

        task = make_task(tmp / "task", task_type=task_type)
        server = FakeToolServer(total_budget)
        result = CompetitionAgent(
            backend_factory=factory,
            llm_client=llm,
            repair_enabled=True,
            max_repair_attempts=max_attempts,
        ).run(task, server, output_root=output_root)
        return result, backends[0], server

    def test_first_repair_success(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, backend, _server = self.run_agent(tmp, FakeLLMClient([llm_ok(FIXED_KERNEL)]))

        self.assertEqual(result.repair_status, "repaired")
        self.assertEqual(result.selected_candidate_id, "c001_repair_llm_01")
        self.assertEqual(result.final_kernel, FIXED_KERNEL)
        self.assertEqual(backend.calls, ["csim", "csim", "synth"])

    def test_first_attempt_fails_second_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, backend, _server = self.run_agent(tmp, FakeLLMClient([llm_ok(BAD_KERNEL), llm_ok(FIXED_KERNEL)]))

        self.assertEqual(result.repair_status, "repaired")
        self.assertEqual(result.selected_candidate_id, "c002_repair_llm_02")
        self.assertEqual([attempt.status for attempt in result.repair_attempts], ["csim_failed", "repaired"])
        self.assertEqual(backend.calls, ["csim", "csim", "csim", "synth"])

    def test_all_repairs_fail_returns_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, _backend, _server = self.run_agent(tmp, FakeLLMClient([llm_ok(BAD_KERNEL), llm_ok(BAD_KERNEL)]))

        self.assertEqual(result.status, "repair_failed")
        self.assertEqual(result.selected_candidate_id, "c000_baseline")
        self.assertEqual(result.final_kernel, BASELINE_KERNEL)
        self.assertEqual(result.stop_reason, "max_attempts_exhausted")

    def test_projection_bugfix_uses_deterministic_repair_before_llm(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            backends: list[FakeBackend] = []

            def factory(task, server):
                backend = FakeBackend(task, server, tmp)
                backends.append(backend)
                return backend

            llm = FakeLLMClient([])
            result = CompetitionAgent(
                backend_factory=factory,
                llm_client=llm,
                repair_enabled=True,
            ).run(make_projection_task(tmp / "task"), FakeToolServer())

        self.assertEqual(len(llm.calls), 0)
        self.assertEqual(result.repair_status, "repaired")
        self.assertEqual(result.selected_candidate_id, "c001_repair_deterministic_01")
        self.assertEqual(result.repair_attempts[0].llm_response.status, "not_called")
        self.assertIn("triangle_3d.z2 / 3", result.final_kernel)
        self.assertEqual(backends[0].calls, ["csim", "csim", "synth"])

    def test_llm_malformed_schema_timeout_and_token_errors_stop_stably(self):
        cases = [
            ("LLMResponseError", "malformed JSON", 1),
            ("LLMResponseError", "schema validation failed", 1),
            ("LLMTimeoutError", "timed out", 1),
            ("TokenLimitError", "token limit", 0),
        ]
        for error_type, message, attempt_count in cases:
            with self.subTest(error=error_type, attempts=attempt_count):
                with tempfile.TemporaryDirectory() as tmp_name:
                    tmp = Path(tmp_name)
                    result, backend, _server = self.run_agent(
                        tmp,
                        FakeLLMClient([llm_error(error_type, message, attempt_count=attempt_count)]),
                        max_attempts=1,
                    )
                self.assertEqual(result.status, "repair_failed")
                self.assertEqual(result.final_kernel, BASELINE_KERNEL)
                self.assertEqual(result.repair_attempts[0].status, "llm_error")
                self.assertEqual(backend.calls, ["csim"])

    def test_llm_error_retries_when_attempt_budget_remains(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, backend, _server = self.run_agent(
                tmp,
                FakeLLMClient([llm_error("LLMTimeoutError", "timed out"), llm_ok(FIXED_KERNEL)]),
                max_attempts=2,
            )

        self.assertEqual(result.repair_status, "repaired")
        self.assertEqual(result.selected_candidate_id, "c002_repair_llm_02")
        self.assertEqual([attempt.status for attempt in result.repair_attempts], ["llm_error", "repaired"])
        self.assertEqual(backend.calls, ["csim", "csim", "synth"])

    def test_validation_failure_retries_from_latest_tool_observed_kernel(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            llm = FakeLLMClient([llm_ok(SIGNATURE_CHANGED_KERNEL), llm_ok(FIXED_KERNEL)])
            result, backend, _server = self.run_agent(tmp, llm, max_attempts=2)

        second_prompt = json.loads(llm.calls[1]["messages"][1]["content"])
        self.assertEqual(second_prompt["editable_kernel"], BASELINE_KERNEL)
        feedback = second_prompt["diagnostics"]["previous_attempt_feedback"]
        self.assertEqual(feedback["stage"], "static_validation")
        self.assertIn("top function signature changed", feedback["errors"])
        self.assertEqual(feedback["original_signature"], "void top(int a,int*b)")
        self.assertEqual(result.repair_status, "repaired")
        self.assertEqual(result.selected_candidate_id, "c002_repair_llm_02")
        self.assertEqual([attempt.status for attempt in result.repair_attempts], ["validation_failed", "repaired"])
        self.assertEqual(backend.calls, ["csim", "csim", "synth"])

    def test_invalid_kernel_does_not_consume_hls_budget_after_llm(self):
        for kernel in ("", SIGNATURE_CHANGED_KERNEL):
            with self.subTest(kernel=kernel):
                with tempfile.TemporaryDirectory() as tmp_name:
                    tmp = Path(tmp_name)
                    result, backend, _server = self.run_agent(tmp, FakeLLMClient([llm_ok(kernel)]), max_attempts=1)
                self.assertEqual(result.status, "repair_failed")
                self.assertEqual(result.repair_attempts[0].status, "validation_failed")
                self.assertEqual(backend.calls, ["csim"])

    def test_hls_budget_insufficient_blocks_llm_before_request(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            llm = FakeLLMClient([llm_ok(FIXED_KERNEL)])
            result, backend, _server = self.run_agent(tmp, llm, total_budget=5)

        self.assertEqual(result.status, "repair_failed")
        self.assertEqual(result.stop_reason, "hls_budget_insufficient")
        self.assertEqual(len(llm.calls), 0)
        self.assertEqual(backend.calls, ["csim"])

    def test_persistent_repair_candidate_lineage_and_baseline_safety(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            output_root = tmp / "runs"
            result, _backend, _server = self.run_agent(
                tmp,
                FakeLLMClient([llm_ok(FIXED_KERNEL)]),
                output_root=output_root,
            )
            run_dir = Path(result.run_directory)
            baseline_kernel = (run_dir / "candidates" / "c000_baseline" / "kernel.cpp").read_text(encoding="utf-8")
            repair_kernel = (run_dir / "candidates" / "c001_repair_llm_01" / "kernel.cpp").read_text(encoding="utf-8")
            final_kernel = (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8")
            repair_manifest = json.loads(
                (run_dir / "candidates" / "c001_repair_llm_01" / "manifest.json").read_text(encoding="utf-8")
            )
            calls = (run_dir / "llm" / "calls.jsonl").read_text(encoding="utf-8")
            summary = json.loads((run_dir / "llm" / "token_summary.json").read_text(encoding="utf-8"))

        self.assertEqual(baseline_kernel, BASELINE_KERNEL)
        self.assertEqual(repair_kernel, FIXED_KERNEL)
        self.assertEqual(final_kernel, FIXED_KERNEL)
        self.assertEqual(repair_manifest["parent_candidate_id"], "c000_baseline")
        self.assertEqual(repair_manifest["lineage"], ["c000_baseline"])
        self.assertIn("fake-open-model", calls)
        self.assertEqual(summary["total_tokens"], 24)

    def test_dot_product_like_optimize_task_does_not_trigger_repair(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            llm = FakeLLMClient([llm_ok(FIXED_KERNEL)])

            def factory(task, server):
                return FakeBackend(task, server, tmp)

            task = make_task(tmp / "task", task_type="optimize", kernel=FIXED_KERNEL)
            result = CompetitionAgent(
                backend_factory=factory,
                llm_client=llm,
                repair_enabled=True,
            ).run(task, FakeToolServer())

        self.assertEqual(result.repair_status, "not_attempted")
        self.assertEqual(len(llm.calls), 0)
        self.assertEqual(result.selected_candidate_id, "c000_baseline")


class FakeHTTPHandler(BaseHTTPRequestHandler):
    response_payload: dict = {}
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        self.__class__.requests.append(json.loads(body))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.__class__.response_payload).encode("utf-8"))

    def log_message(self, fmt, *args):
        return


class FakeHTTPServer:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self):
        FakeHTTPHandler.response_payload = self.payload
        FakeHTTPHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHTTPHandler)
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
        return len(FakeHTTPHandler.requests)


def fake_http_payload(kernel: str) -> dict:
    content = json.dumps(
        {
            "diagnosis": "angle 0 omitted z2 contribution",
            "replacement_kernel": kernel,
            "changes": ["add z2 / 3 to angle 0 z average"],
            "confidence": "high",
        }
    )
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 75, "total_tokens": 125},
    }


def llm_config(base_url: str) -> LLMConfig:
    return LLMConfig(
        base_url=base_url,
        model="fake-open-repair-model",
        api_key=None,
        timeout_seconds=5.0,
        max_output_tokens=4096,
        temperature=0.0,
        license="Apache-2.0",
        source="local-fake-http",
        model_version="test",
        max_retries=0,
        max_call_total_tokens=None,
        max_total_tokens=None,
    )


@unittest.skipUnless(os.environ.get("FPT26_RUN_HLS_TESTS") == "1", "set FPT26_RUN_HLS_TESTS=1 to run Vitis HLS tests")
class RepairControllerHlsTests(unittest.TestCase):
    def test_projection_bugfix_repaired_with_fake_http_model(self):
        from llm4hls.budget import Budget
        from llm4hls.harness import ToolServer
        from llm4hls.task import load_task

        task = load_task(Path("fpt26-harness/tasks/projection_bugfix"))
        fixed_kernel = Path("fpt26-harness/tasks/projection_bugfix/reference/projection.cpp").read_text(encoding="utf-8")
        with FakeHTTPServer(fake_http_payload(fixed_kernel)) as server:
            llm_client = LLMClient(config=llm_config(server.base_url), token_tracker=TokenTracker())
            tool_server = ToolServer(
                task,
                Budget(task.budget),
                Path("fpt26-agent/runs/repair_controller_hls/projection_bugfix/tools"),
            )
            result = CompetitionAgent(
                llm_client=llm_client,
                repair_enabled=True,
                max_repair_attempts=1,
            ).run(task, tool_server, output_root=Path("fpt26-agent/runs/repair_controller_hls/persist"))

        self.assertEqual(server.request_count, 1)
        self.assertEqual(result.repair_status, "repaired")
        self.assertEqual(result.selected_candidate_id, "c001_repair_llm_01")
        self.assertEqual([stage.status for stage in result.stage_results], ["runtime_fail", "pass", "pass"])
        self.assertEqual(result.repair_attempts[0].stage_results[0].status, "pass")
        self.assertEqual(result.repair_attempts[0].stage_results[1].status, "pass")
        run_dir = Path(result.run_directory)
        self.assertEqual((run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8"), fixed_kernel)
        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["repair_status"], "repaired")
        self.assertEqual(manifest["llm_usage"]["total_tokens"], 125)


@unittest.skipUnless(
    os.environ.get("FPT26_RUN_HLS_TESTS") == "1" and os.environ.get("FPT26_RUN_LLM_TESTS") == "1",
    "set both FPT26_RUN_HLS_TESTS=1 and FPT26_RUN_LLM_TESTS=1 to run real LLM repair",
)
class RepairControllerRealLLMTests(unittest.TestCase):
    def test_projection_bugfix_real_llm_single_attempt(self):
        required = [
            "FPT26_LLM_BASE_URL",
            "FPT26_LLM_MODEL",
            "FPT26_LLM_TIMEOUT_SECONDS",
            "FPT26_LLM_MAX_OUTPUT_TOKENS",
            "FPT26_LLM_TEMPERATURE",
            "FPT26_LLM_LICENSE",
            "FPT26_LLM_SOURCE",
        ]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            self.skipTest("missing real LLM config: " + ", ".join(missing))

        from llm4hls.budget import Budget
        from llm4hls.harness import ToolServer
        from llm4hls.task import load_task

        task = load_task(Path("fpt26-harness/tasks/projection_bugfix"))
        tool_server = ToolServer(
            task,
            Budget(task.budget),
            Path("fpt26-agent/runs/repair_controller_real_llm/projection_bugfix/tools"),
        )
        result = CompetitionAgent(
            llm_client=LLMClient(),
            repair_enabled=True,
            max_repair_attempts=1,
        ).run(task, tool_server, output_root=Path("fpt26-agent/runs/repair_controller_real_llm/persist"))

        self.assertLessEqual(len(result.repair_attempts), 1)
        self.assertNotIn(os.environ.get("FPT26_LLM_API_KEY", "__no_key__"), json.dumps(result.to_dict()))


if __name__ == "__main__":
    unittest.main()
