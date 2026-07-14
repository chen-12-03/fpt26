from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from agent.analysis.stream_analyzer import StreamAnalyzer
from agent.competition_agent import CompetitionAgent
from agent.execution.result_adapter import UnifiedToolResult
from agent.input.task_adapter import TaskAdapter
from agent.llm.config import LLMConfig
from agent.llm.llm_client import LLMClient
from agent.llm.schemas import LLMCallRecord, LLMResponse
from agent.llm.token_tracker import TokenTracker


PART = "xcu55c-fsvh2892-2L-e"

BASELINE_KERNEL = """#include "kernel.h"
#include "hls_stream.h"

static void feed_alpha(data_t in[N], hls::stream<data_t> &left_lane,
                       hls::stream<data_t> &right_lane) {
    for (int i = 0; i < N; i++) left_lane.write(in[i]);
    for (int i = 0; i < N; i++) right_lane.write(in[i]);
}

static void double_alpha(hls::stream<data_t> &left_lane,
                         hls::stream<data_t> &middle_lane) {
    for (int i = 0; i < N; i++) middle_lane.write(left_lane.read() * 2);
}

static void join_alpha(hls::stream<data_t> &middle_lane,
                       hls::stream<data_t> &right_lane,
                       data_t out[N]) {
    for (int i = 0; i < N; i++) out[i] = middle_lane.read() + right_lane.read();
}

void top(data_t in[N], data_t out[N]) {
#pragma HLS DATAFLOW
    hls::stream<data_t> left_lane, middle_lane, right_lane;
    feed_alpha(in, left_lane, right_lane);
    double_alpha(left_lane, middle_lane);
    join_alpha(middle_lane, right_lane, out);
}
"""

FIXED_KERNEL = """#include "kernel.h"
#include "hls_stream.h"

static void feed_alpha(data_t in[N], hls::stream<data_t> &left_lane,
                       hls::stream<data_t> &right_lane) {
    for (int i = 0; i < N; i++) {
        left_lane.write(in[i]);
        right_lane.write(in[i]);
    }
}

static void double_alpha(hls::stream<data_t> &left_lane,
                         hls::stream<data_t> &middle_lane) {
    for (int i = 0; i < N; i++) middle_lane.write(left_lane.read() * 2);
}

static void join_alpha(hls::stream<data_t> &middle_lane,
                       hls::stream<data_t> &right_lane,
                       data_t out[N]) {
    for (int i = 0; i < N; i++) out[i] = middle_lane.read() + right_lane.read();
}

void top(data_t in[N], data_t out[N]) {
#pragma HLS DATAFLOW
    hls::stream<data_t> left_lane, middle_lane, right_lane;
    feed_alpha(in, left_lane, right_lane);
    double_alpha(left_lane, middle_lane);
    join_alpha(middle_lane, right_lane, out);
}
// PAIR_WRITE
"""

COSIM_FAIL_KERNEL = FIXED_KERNEL.replace("// PAIR_WRITE\n", "// VALID_BUT_COSIM_FAIL\n")
CSIM_FAIL_KERNEL = FIXED_KERNEL.replace("// PAIR_WRITE\n", "// CSIM_FAIL\n")
SYNTH_FAIL_KERNEL = FIXED_KERNEL.replace("// PAIR_WRITE\n", "// SYNTH_FAIL\n")
COSIM_TIMEOUT_KERNEL = FIXED_KERNEL.replace("// PAIR_WRITE\n", "// COSIM_TIMEOUT\n")
SIGNATURE_CHANGED_KERNEL = FIXED_KERNEL.replace(
    "void top(data_t in[N], data_t out[N])",
    "void top(data_t in[N], data_t out[N], int extra)",
)


class FakeBudget:
    def __init__(self, total: int = 80) -> None:
        self.total = total
        self.spent = 0
        self.cost = {"csim": 1, "synth": 4, "cosim": 20}
        self.calls: list[SimpleNamespace] = []

    def remaining(self) -> int:
        return self.total - self.spent

    def charge(self, kind: str) -> tuple[int, int]:
        before = self.spent
        cost = self.cost[kind]
        self.spent += cost
        self.calls.append(SimpleNamespace(kind=kind, cost=cost, spent_after=self.spent))
        return before, self.spent


class FakeToolServer:
    def __init__(self, total_budget: int = 80) -> None:
        self.budget = FakeBudget(total_budget)
        self.transcript: list[SimpleNamespace] = []


class FakeBackend:
    def __init__(self, _task, tool_server, log_dir: Path, *, baseline_cosim_log: str | None = None) -> None:
        self.tool_server = tool_server
        self.log_dir = log_dir
        self.baseline_cosim_log = baseline_cosim_log or (
            "ERROR: deadlock detected in DATAFLOW channel right_lane FIFO blocked write\n"
        )
        self.calls: list[str] = []
        self.kernel_inputs: list[str] = []

    def csim(self, kernel_code: str) -> UnifiedToolResult:
        if "CSIM_FAIL" in kernel_code:
            return self._result(kernel_code, "csim", "runtime_fail", "Mismatch expected 3 actual 4\n")
        return self._result(kernel_code, "csim", "pass", "C simulation passed\n")

    def synth(self, kernel_code: str) -> UnifiedToolResult:
        if "SYNTH_FAIL" in kernel_code:
            return self._result(kernel_code, "synth", "synth_error", "ERROR: synthesis failed\n")
        return self._result(kernel_code, "synth", "pass", "Synthesis passed\n", metrics={"latency_max": 32, "ii_max": 1})

    def cosim(self, kernel_code: str) -> UnifiedToolResult:
        if "PAIR_WRITE" in kernel_code:
            return self._result(kernel_code, "cosim", "pass", "Co-simulation passed\n")
        if "COSIM_TIMEOUT" in kernel_code:
            return self._result(kernel_code, "cosim", "timeout", "Cosim timed out while DATAFLOW stream right_lane stalled\n")
        return self._result(kernel_code, "cosim", "cosim_fail", self.baseline_cosim_log)

    def _result(
        self,
        kernel_code: str,
        stage: str,
        status: str,
        log_text: str,
        *,
        metrics: dict | None = None,
    ) -> UnifiedToolResult:
        self.calls.append(stage)
        self.kernel_inputs.append(kernel_code)
        before, after = self.tool_server.budget.charge(stage)
        self.tool_server.transcript.append(
            SimpleNamespace(
                n=len(self.tool_server.transcript) + 1,
                kind=stage,
                phase=status,
                spent=after,
                detail=f"[{stage}] {status}",
            )
        )
        run_dir = self.log_dir / f"{stage}_{len(self.calls)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "tool.log"
        log_path.write_text(log_text, encoding="utf-8")
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        artifacts = {"run_dir": str(run_dir), "tool_log": str(log_path)}
        if stage == "cosim":
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


def structural_llm_ok(
    kernel: str,
    *,
    diagnosis: str = "producer writes two streams in separate bursts",
    strategy: str = "pair writes in the same producer loop",
    affected_streams: list[str] | None = None,
    confidence: str = "high",
) -> LLMResponse:
    parsed = {
        "diagnosis": diagnosis,
        "repair_strategy": strategy,
        "affected_streams": affected_streams or ["left_lane", "right_lane"],
        "replacement_kernel": kernel,
        "changes": ["write both streams from feed_alpha in one loop"],
        "confidence": confidence,
    }
    content = json.dumps(parsed)
    prompt = "2" * 64
    record = LLMCallRecord(
        purpose="structural_repair",
        model="fake-open-structural-model",
        model_version="test",
        license="Apache-2.0",
        source="fake",
        prompt_sha256=prompt,
        attempt_index=1,
        status="ok",
        http_status=200,
        input_tokens=17,
        output_tokens=19,
        total_tokens=36,
        usage_source="api",
        elapsed_seconds=0.01,
        error_type=None,
        error_message=None,
    )
    return LLMResponse(
        status="ok",
        content=content,
        parsed=parsed,
        model="fake-open-structural-model",
        purpose="structural_repair",
        prompt_sha256=prompt,
        input_tokens=17,
        output_tokens=19,
        total_tokens=36,
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


def structural_llm_error(error_type: str, message: str, *, attempt_count: int = 1) -> LLMResponse:
    prompt = "3" * 64
    attempts = []
    if attempt_count:
        attempts.append(
            LLMCallRecord(
                purpose="structural_repair",
                model="fake-open-structural-model",
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
        model="fake-open-structural-model",
        purpose="structural_repair",
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


def make_task(
    tmp: Path,
    *,
    task_type: str = "structural",
    requires_cosim: bool = True,
    kernel: str = BASELINE_KERNEL,
):
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "kernel.cpp").write_text(kernel, encoding="utf-8")
    (tmp / "kernel.h").write_text("typedef int data_t;\nconst int N = 8;\nvoid top(data_t in[N], data_t out[N]);\n", encoding="utf-8")
    (tmp / "tb.cpp").write_text(
        "int main(){data_t a[N]={0}; data_t b[N]={0}; top(a,b); return 0;}\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        dir=tmp,
        id="unit_structural",
        type=task_type,
        difficulty=1,
        top="top",
        budget=80,
        part=PART,
        clock_ns=5.0,
        requires_cosim=requires_cosim,
        initial_condition="",
        description="Fix a dataflow stream scheduling issue without changing the interface.",
        kernel_name="kernel.cpp",
        kernel_code=kernel,
        headers={"kernel.h": "typedef int data_t;\nconst int N = 8;\nvoid top(data_t in[N], data_t out[N]);\n"},
        public_tb_name="tb.cpp",
        public_tb_code="int main(){data_t a[N]={0}; data_t b[N]={0}; top(a,b); return 0;}\n",
    )


class StructuralRepairFakeTests(unittest.TestCase):
    def run_agent(
        self,
        tmp: Path,
        llm: FakeLLMClient,
        *,
        task_type: str = "structural",
        requires_cosim: bool = True,
        total_budget: int = 80,
        baseline_cosim_log: str | None = None,
        output_root: Path | None = None,
        enabled: bool = True,
        max_attempts: int = 2,
    ):
        backends: list[FakeBackend] = []

        def factory(task, server):
            backend = FakeBackend(task, server, tmp, baseline_cosim_log=baseline_cosim_log)
            backends.append(backend)
            return backend

        task = make_task(tmp / "task", task_type=task_type, requires_cosim=requires_cosim)
        server = FakeToolServer(total_budget)
        result = CompetitionAgent(
            backend_factory=factory,
            llm_client=llm,
            structural_repair_enabled=enabled,
            max_structural_repair_attempts=max_attempts,
        ).run(task, server, output_root=output_root)
        return result, backends[0], server

    def test_first_structural_repair_success(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, backend, _server = self.run_agent(tmp, FakeLLMClient([structural_llm_ok(FIXED_KERNEL)]))

        self.assertEqual(result.structural_repair_status, "repaired")
        self.assertEqual(result.selected_candidate_id, "c001_structural_llm_01")
        self.assertEqual(result.final_kernel, FIXED_KERNEL)
        self.assertEqual(result.final_cosim_diagnosis.category, "none")
        self.assertEqual([stage.status for stage in result.stage_results], ["pass", "pass", "cosim_fail", "pass", "pass", "pass"])
        self.assertEqual(backend.calls, ["csim", "synth", "cosim", "csim", "synth", "cosim"])

    def test_first_cosim_fails_second_structural_repair_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, backend, _server = self.run_agent(
                tmp,
                FakeLLMClient([structural_llm_ok(COSIM_FAIL_KERNEL), structural_llm_ok(FIXED_KERNEL)]),
            )

        self.assertEqual(result.structural_repair_status, "repaired")
        self.assertEqual(result.selected_candidate_id, "c002_structural_llm_02")
        self.assertEqual([attempt.status for attempt in result.structural_repair_attempts], ["cosim_failed", "repaired"])
        self.assertEqual(backend.calls, ["csim", "synth", "cosim", "csim", "synth", "cosim", "csim", "synth", "cosim"])

    def test_all_structural_repairs_fail_returns_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, _backend, _server = self.run_agent(
                tmp,
                FakeLLMClient([structural_llm_ok(COSIM_FAIL_KERNEL), structural_llm_ok(COSIM_FAIL_KERNEL)]),
            )

        self.assertEqual(result.status, "structural_repair_failed")
        self.assertEqual(result.structural_repair_status, "failed")
        self.assertEqual(result.selected_candidate_id, "c000_baseline")
        self.assertEqual(result.final_kernel, BASELINE_KERNEL)
        self.assertEqual(result.stop_reason, "max_attempts_exhausted")

    def test_llm_errors_stop_without_losing_baseline(self):
        cases = [
            ("LLMResponseError", "malformed JSON", 1),
            ("LLMResponseError", "schema validation failed", 1),
            ("LLMTimeoutError", "timed out", 1),
            ("TokenLimitError", "token limit", 0),
        ]
        for error_type, message, attempt_count in cases:
            with self.subTest(error=error_type):
                with tempfile.TemporaryDirectory() as tmp_name:
                    tmp = Path(tmp_name)
                    result, backend, _server = self.run_agent(
                        tmp,
                        FakeLLMClient(
                            [structural_llm_error(error_type, message, attempt_count=attempt_count)]
                        ),
                    )
            self.assertEqual(result.status, "structural_repair_failed")
            self.assertEqual(result.final_kernel, BASELINE_KERNEL)
            self.assertEqual(result.structural_repair_attempts[0].status, "llm_error")
            self.assertEqual(backend.calls, ["csim", "synth", "cosim"])

    def test_invalid_kernel_does_not_consume_candidate_hls_budget(self):
        for kernel in ("", SIGNATURE_CHANGED_KERNEL, "```cpp\n" + FIXED_KERNEL + "\n```"):
            with self.subTest(kind=kernel[:12]):
                with tempfile.TemporaryDirectory() as tmp_name:
                    tmp = Path(tmp_name)
                    result, backend, _server = self.run_agent(
                        tmp,
                        FakeLLMClient([structural_llm_ok(kernel)]),
                        max_attempts=1,
                    )
                self.assertEqual(result.status, "structural_repair_failed")
                self.assertEqual(result.structural_repair_attempts[0].status, "validation_failed")
                self.assertEqual(backend.calls, ["csim", "synth", "cosim"])

    def test_csim_failure_does_not_run_synth_or_cosim_for_candidate(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, backend, _server = self.run_agent(
                tmp,
                FakeLLMClient([structural_llm_ok(CSIM_FAIL_KERNEL)]),
                max_attempts=1,
            )

        self.assertEqual(result.structural_repair_attempts[0].status, "csim_failed")
        self.assertEqual(backend.calls, ["csim", "synth", "cosim", "csim"])

    def test_synth_failure_does_not_run_cosim_for_candidate(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, backend, _server = self.run_agent(
                tmp,
                FakeLLMClient([structural_llm_ok(SYNTH_FAIL_KERNEL)]),
                max_attempts=1,
            )

        self.assertEqual(result.structural_repair_attempts[0].status, "synth_failed")
        self.assertEqual(backend.calls, ["csim", "synth", "cosim", "csim", "synth"])

    def test_cosim_timeout_is_recorded_and_returns_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, _backend, _server = self.run_agent(
                tmp,
                FakeLLMClient([structural_llm_ok(COSIM_TIMEOUT_KERNEL)]),
                max_attempts=1,
            )

        attempt = result.structural_repair_attempts[0]
        self.assertEqual(attempt.status, "cosim_failed")
        self.assertEqual(attempt.cosim_diagnosis.category, "deadlock")
        self.assertEqual(result.final_kernel, BASELINE_KERNEL)

    def test_hls_budget_insufficient_blocks_llm_before_request(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            llm = FakeLLMClient([structural_llm_ok(FIXED_KERNEL)])
            result, backend, _server = self.run_agent(tmp, llm, total_budget=30)

        self.assertEqual(result.structural_repair_status, "failed")
        self.assertEqual(result.stop_reason, "hls_budget_insufficient")
        self.assertEqual(len(llm.calls), 0)
        self.assertEqual(backend.calls, ["csim", "synth", "cosim"])

    def test_non_structural_cosim_failure_does_not_trigger_structural_repair(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            llm = FakeLLMClient([structural_llm_ok(FIXED_KERNEL)])
            result, backend, _server = self.run_agent(
                tmp,
                llm,
                baseline_cosim_log="Cosim mismatch at output 0 expected 3 actual 4\n",
            )

        self.assertEqual(result.requires_structural_repair, False)
        self.assertEqual(result.structural_repair_status, "not_attempted")
        self.assertEqual(result.final_kernel, BASELINE_KERNEL)
        self.assertEqual(len(llm.calls), 0)
        self.assertEqual(backend.calls, ["csim", "synth", "cosim"])

    def test_structural_repair_disabled_keeps_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            llm = FakeLLMClient([structural_llm_ok(FIXED_KERNEL)])
            result, backend, _server = self.run_agent(tmp, llm, enabled=False)

        self.assertEqual(result.structural_repair_status, "not_attempted")
        self.assertEqual(result.final_kernel, BASELINE_KERNEL)
        self.assertEqual(len(llm.calls), 0)
        self.assertEqual(backend.calls, ["csim", "synth", "cosim"])

    def test_dot_product_like_optimize_task_does_not_trigger_structural_repair(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            llm = FakeLLMClient([structural_llm_ok(FIXED_KERNEL)])
            result, backend, _server = self.run_agent(
                tmp,
                llm,
                task_type="optimize",
                requires_cosim=True,
            )

        self.assertEqual(result.structural_repair_status, "not_attempted")
        self.assertEqual(len(llm.calls), 0)
        self.assertEqual(backend.calls, ["csim", "synth"])

    def test_persistence_writes_structural_candidate_lineage_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            output_root = tmp / "runs"
            result, _backend, _server = self.run_agent(
                tmp,
                FakeLLMClient([structural_llm_ok(FIXED_KERNEL)]),
                output_root=output_root,
            )
            run_dir = Path(result.run_directory)
            baseline_kernel = (run_dir / "candidates" / "c000_baseline" / "kernel.cpp").read_text(encoding="utf-8")
            repair_kernel = (run_dir / "candidates" / "c001_structural_llm_01" / "kernel.cpp").read_text(encoding="utf-8")
            final_kernel = (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8")
            repair_manifest = json.loads(
                (run_dir / "candidates" / "c001_structural_llm_01" / "manifest.json").read_text(encoding="utf-8")
            )
            stream_analysis = json.loads(
                (run_dir / "candidates" / "c001_structural_llm_01" / "stream_analysis.json").read_text(encoding="utf-8")
            )
            summary = json.loads((run_dir / "structural_repair" / "summary.json").read_text(encoding="utf-8"))
            attempts = json.loads((run_dir / "structural_repair" / "attempts.json").read_text(encoding="utf-8"))
            llm_calls = (run_dir / "llm" / "calls.jsonl").read_text(encoding="utf-8")
            token_summary = json.loads((run_dir / "llm" / "token_summary.json").read_text(encoding="utf-8"))
            run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(baseline_kernel, BASELINE_KERNEL)
        self.assertEqual(repair_kernel, FIXED_KERNEL)
        self.assertEqual(final_kernel, FIXED_KERNEL)
        self.assertEqual(repair_manifest["parent_candidate_id"], "c000_baseline")
        self.assertEqual(repair_manifest["lineage"], ["c000_baseline"])
        self.assertEqual(repair_manifest["selection_status"], "selected")
        self.assertIn("right_lane", stream_analysis["stream_element_types"])
        self.assertEqual(summary["status"], "repaired")
        self.assertEqual(attempts[0]["candidate"]["candidate_id"], "c001_structural_llm_01")
        self.assertIn("fake-open-structural-model", llm_calls)
        self.assertEqual(token_summary["total_tokens"], 36)
        self.assertEqual(run_manifest["structural_repair_status"], "repaired")
        self.assertEqual(run_manifest["final_cosim_diagnosis"]["category"], "none")


class StreamAnalyzerTests(unittest.TestCase):
    def test_stream_analyzer_reports_renamed_streams_and_imbalance_hints(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            context = TaskAdapter.from_official_task(make_task(Path(tmp_name) / "task"))
            analysis = StreamAnalyzer().analyze(context, BASELINE_KERNEL)

        names = {entry["name"] for entry in analysis.stream_declarations}
        self.assertEqual(names, {"left_lane", "middle_lane", "right_lane"})
        self.assertIn("feed_alpha", {entry["function"] for entry in analysis.producer_functions["right_lane"]})
        self.assertIn("join_alpha", {entry["function"] for entry in analysis.consumer_functions["right_lane"]})
        self.assertTrue(
            any(hint.get("kind") == "separate_stream_write_loops" and hint.get("function") == "feed_alpha"
                for hint in analysis.possible_producer_consumer_imbalance)
        )
        self.assertEqual(json.loads(json.dumps(analysis.to_dict(), sort_keys=True)), analysis.to_dict())


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
            "diagnosis": "stage A writes two streams in isolated bursts",
            "repair_strategy": "write the paired streams in one loop to maintain bounded FIFO balance",
            "affected_streams": ["s_main", "s_skip"],
            "replacement_kernel": kernel,
            "changes": ["combine the two stageA write loops"],
            "confidence": "high",
        }
    )
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 80, "completion_tokens": 90, "total_tokens": 170},
    }


def llm_config(base_url: str) -> LLMConfig:
    return LLMConfig(
        base_url=base_url,
        model="fake-open-structural-model",
        api_key=None,
        timeout_seconds=5.0,
        max_output_tokens=8192,
        temperature=0.0,
        license="Apache-2.0",
        source="local-fake-http",
        model_version="test",
        max_retries=0,
        max_call_total_tokens=None,
        max_total_tokens=None,
    )


@unittest.skipUnless(
    os.environ.get("FPT26_RUN_HLS_TESTS") == "1" and os.environ.get("FPT26_RUN_COSIM_TESTS") == "1",
    "set FPT26_RUN_HLS_TESTS=1 and FPT26_RUN_COSIM_TESTS=1 to run Vitis co-sim repair tests",
)
class StructuralRepairOfficialHlsTests(unittest.TestCase):
    def test_residual_stream_deadlock_repaired_with_fake_http_model(self):
        from llm4hls.budget import Budget
        from llm4hls.harness import ToolServer
        from llm4hls.task import load_task

        task = load_task(Path("fpt26-harness/tasks/residual_stream_deadlock"))
        fixed_kernel = Path("fpt26-harness/tasks/residual_stream_deadlock/reference/residual.cpp").read_text(
            encoding="utf-8"
        )
        run_root = Path("fpt26-agent/runs/structural_repair_hls/residual_stream_deadlock/tools")
        output_root = Path("fpt26-agent/runs/structural_repair_hls/persist")
        with FakeHTTPServer(fake_http_payload(fixed_kernel)) as server:
            llm_client = LLMClient(config=llm_config(server.base_url), token_tracker=TokenTracker())
            tool_server = ToolServer(task, Budget(task.budget), run_root)
            result = CompetitionAgent(
                llm_client=llm_client,
                structural_repair_enabled=True,
                max_structural_repair_attempts=1,
            ).run(task, tool_server, output_root=output_root)

        self.assertEqual(server.request_count, 1)
        self.assertEqual(result.structural_repair_status, "repaired")
        self.assertEqual(result.selected_candidate_id, "c001_structural_llm_01")
        self.assertEqual(result.baseline_cosim_diagnosis.requires_structural_repair, True)
        self.assertEqual(result.final_cosim_diagnosis.category, "none")
        self.assertEqual(result.structural_repair_attempts[0].stage_results[-1].status, "pass")
        run_dir = Path(result.run_directory)
        self.assertEqual((run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8"), fixed_kernel)
        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["structural_repair_status"], "repaired")
        self.assertEqual(manifest["llm_usage"]["total_tokens"], 170)


@unittest.skipUnless(
    os.environ.get("FPT26_RUN_HLS_TESTS") == "1" and os.environ.get("FPT26_RUN_LLM_TESTS") == "1",
    "set both FPT26_RUN_HLS_TESTS=1 and FPT26_RUN_LLM_TESTS=1 to run real LLM structural repair",
)
class StructuralRepairRealLLMTests(unittest.TestCase):
    def test_residual_stream_deadlock_real_llm_single_attempt(self):
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

        task = load_task(Path("fpt26-harness/tasks/residual_stream_deadlock"))
        tool_server = ToolServer(
            task,
            Budget(task.budget),
            Path("fpt26-agent/runs/structural_repair_real_llm/residual_stream_deadlock/tools"),
        )
        result = CompetitionAgent(
            llm_client=LLMClient(),
            structural_repair_enabled=True,
            max_structural_repair_attempts=1,
        ).run(task, tool_server, output_root=Path("fpt26-agent/runs/structural_repair_real_llm/persist"))

        self.assertLessEqual(len(result.structural_repair_attempts), 1)
        self.assertNotIn(os.environ.get("FPT26_LLM_API_KEY", "__no_key__"), json.dumps(result.to_dict()))


if __name__ == "__main__":
    unittest.main()
