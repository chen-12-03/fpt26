from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent.analysis.cosim_analyzer import CoSimAnalyzer
from agent.analysis.log_normalizer import LogNormalizer
from agent.competition_agent import CompetitionAgent
from agent.execution.result_adapter import UnifiedToolResult
from agent.input.task_adapter import TaskAdapter


PART = "xcu55c-fsvh2892-2L-e"
BASELINE_KERNEL = """#include "kernel.h"
void top(int in[8], int out[8]) {
    for (int i = 0; i < 8; i++) out[i] = in[i];
}
"""


class FakeBudget:
    def __init__(self, total: int = 40) -> None:
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
    def __init__(self, total_budget: int = 40) -> None:
        self.budget = FakeBudget(total_budget)
        self.transcript: list[SimpleNamespace] = []


class FakeBackend:
    def __init__(self, _task, tool_server, *, log_dir: Path, plan: dict[str, UnifiedToolResult] | None = None) -> None:
        self.tool_server = tool_server
        self.log_dir = log_dir
        self.plan = plan or {}
        self.calls: list[str] = []
        self.kernel_inputs: list[str] = []

    def csim(self, kernel_code: str) -> UnifiedToolResult:
        return self._run("csim", kernel_code, "pass", "C simulation passed\n")

    def synth(self, kernel_code: str) -> UnifiedToolResult:
        return self._run("synth", kernel_code, "pass", "Synthesis passed\n")

    def cosim(self, kernel_code: str) -> UnifiedToolResult:
        return self._run(
            "cosim",
            kernel_code,
            "cosim_fail",
            "ERROR: deadlock detected in DATAFLOW channel s_alpha FIFO blocked write\n",
        )

    def _run(self, stage: str, kernel_code: str, default_status: str, default_log: str) -> UnifiedToolResult:
        self.calls.append(stage)
        self.kernel_inputs.append(kernel_code)
        result = self.plan.get(stage)
        if result is not None:
            if result.status != "budget_exceeded":
                self._charge(stage, result.status, result.summary)
            return result
        self._charge(stage, default_status, f"[{stage}] {default_status}")
        run_dir = self.log_dir / f"{stage}_{len(self.calls)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "tool.log"
        log_path.write_text(default_log, encoding="utf-8")
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        return UnifiedToolResult(
            stage=stage,
            status=default_status,
            return_code=0 if default_status == "pass" else 1,
            elapsed_seconds=0.2,
            summary=f"[{stage}] {default_status}",
            metrics={},
            artifacts={"run_dir": str(run_dir), "tool_log": str(log_path), "cosim_report_dir": str(report_dir)}
            if stage == "cosim"
            else {"run_dir": str(run_dir), "tool_log": str(log_path)},
            budget_before=0,
            budget_after=self.tool_server.budget.spent,
        )

    def _charge(self, stage: str, status: str, summary: str) -> None:
        self.tool_server.budget.charge(stage)
        self.tool_server.transcript.append(
            SimpleNamespace(
                n=len(self.tool_server.transcript) + 1,
                kind=stage,
                phase=status,
                spent=self.tool_server.budget.spent,
                detail=summary,
            )
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
    (tmp / "kernel.h").write_text("void top(int in[8], int out[8]);\n", encoding="utf-8")
    (tmp / "tb.cpp").write_text("int main(){int a[8]={0}; int b[8]={0}; top(a,b); return 0;}\n", encoding="utf-8")
    return SimpleNamespace(
        dir=tmp,
        id="unit_cosim",
        type=task_type,
        difficulty=1,
        top="top",
        budget=40,
        part=PART,
        clock_ns=5.0,
        requires_cosim=requires_cosim,
        initial_condition="",
        description="Unit cosim task.",
        kernel_name="kernel.cpp",
        kernel_code=kernel,
        headers={"kernel.h": "void top(int in[8], int out[8]);\n"},
        public_tb_name="tb.cpp",
        public_tb_code="int main(){int a[8]={0}; int b[8]={0}; top(a,b); return 0;}\n",
    )


def make_result(stage: str, status: str, tmp: Path, log_text: str = "") -> UnifiedToolResult:
    run_dir = tmp / f"{stage}_result_{status}"
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {"run_dir": str(run_dir)}
    if log_text:
        log_path = run_dir / "tool.log"
        log_path.write_text(log_text, encoding="utf-8")
        artifacts["tool_log"] = str(log_path)
    return UnifiedToolResult(
        stage=stage,
        status=status,
        return_code=0 if status == "pass" else 1,
        elapsed_seconds=0.1,
        summary=f"[{stage}] {status}",
        metrics={},
        artifacts=artifacts,
        budget_before=0,
        budget_after=0,
    )


class CosimBaselineFakeTests(unittest.TestCase):
    def run_agent(
        self,
        tmp: Path,
        *,
        task_type: str = "structural",
        requires_cosim: bool = True,
        total_budget: int = 40,
        plan: dict[str, UnifiedToolResult] | None = None,
        output_root: Path | None = None,
    ):
        backends: list[FakeBackend] = []

        def factory(task, server):
            backend = FakeBackend(task, server, log_dir=tmp, plan=plan)
            backends.append(backend)
            return backend

        task = make_task(tmp / "task", task_type=task_type, requires_cosim=requires_cosim)
        server = FakeToolServer(total_budget)
        result = CompetitionAgent(backend_factory=factory).run(task, server, output_root=output_root)
        return result, backends[0], server

    def test_structural_task_runs_baseline_cosim_and_classifies_deadlock(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, backend, server = self.run_agent(Path(tmp_name))

        self.assertEqual(backend.calls, ["csim", "synth", "cosim"])
        self.assertEqual(result.cosim_decision.reason, "requires_cosim_structural_baseline")
        self.assertEqual(result.cosim_diagnosis.category, "deadlock")
        self.assertEqual(result.initial_condition.condition, "structural_failure")
        self.assertTrue(result.requires_structural_repair)
        self.assertEqual([entry["kind"] for entry in result.budget["transcript"]], ["csim", "synth", "cosim"])
        self.assertEqual(result.budget["spent"], server.budget.spent)

    def test_csim_failure_stops_before_synth_and_cosim(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            plan = {"csim": make_result("csim", "runtime_fail", tmp, "Mismatch expected 1 actual 2\n")}
            result, backend, _server = self.run_agent(tmp, plan=plan)

        self.assertEqual(backend.calls, ["csim"])
        self.assertIsNone(result.cosim_decision)
        self.assertEqual(result.initial_condition.condition, "csim_failure")

    def test_synth_failure_stops_before_cosim(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            plan = {"synth": make_result("synth", "synth_error", tmp, "ERROR: synthesis failed\n")}
            result, backend, _server = self.run_agent(tmp, plan=plan)

        self.assertEqual(backend.calls, ["csim", "synth"])
        self.assertIsNone(result.cosim_decision)
        self.assertEqual(result.initial_condition.condition, "synth_failure")

    def test_budget_insufficient_does_not_call_cosim(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, backend, server = self.run_agent(Path(tmp_name), total_budget=5)

        self.assertEqual(backend.calls, ["csim", "synth"])
        self.assertEqual(result.cosim_decision.reason, "insufficient_budget")
        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(result.initial_condition.condition, "budget_exceeded")
        self.assertEqual([entry.kind for entry in server.transcript], ["csim", "synth"])

    def test_optimize_task_does_not_run_baseline_cosim_unconditionally(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, backend, _server = self.run_agent(Path(tmp_name), task_type="optimize", requires_cosim=True)

        self.assertEqual(backend.calls, ["csim", "synth"])
        self.assertEqual(result.cosim_decision.reason, "task_type_not_baseline_cosim")
        self.assertIsNone(result.cosim_diagnosis)

    def test_cosim_analyzer_categories_are_evidence_driven(self):
        cases = [
            ("deadlock", "ERROR: deadlock detected on stream s_dead\n", "deadlock"),
            ("underflow", "RTL stream s_in underflow: read from empty FIFO\n", "stream_underflow"),
            ("overflow", "FIFO s_out overflow, stream full and blocked write\n", "stream_overflow"),
            ("protocol", "AXI protocol error: handshake violation\n", "protocol_error"),
            ("mismatch", "Cosim mismatch at 3: expected 1 actual 2\n", "cosim_mismatch"),
            ("timeout_structural", "Simulation timed out while DATAFLOW channel s_mid stalled\n", "deadlock"),
            ("timeout_plain", "Simulation timed out after limit\n", "timeout"),
        ]
        analyzer = CoSimAnalyzer()
        normalizer = LogNormalizer()
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            context = TaskAdapter.from_official_task(make_task(tmp / "task"))
            for name, log_text, expected in cases:
                status = "timeout" if name.startswith("timeout") else "cosim_fail"
                result = make_result("cosim", status, tmp, log_text)
                diagnosis = analyzer.analyze(context, result, normalizer.normalize(result))
                self.assertEqual(diagnosis.category, expected)
                if expected in {"deadlock", "stream_underflow", "stream_overflow"}:
                    self.assertTrue(diagnosis.affected_streams)

    def test_missing_log_returns_unknown(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            context = TaskAdapter.from_official_task(make_task(tmp / "task"))
            result = UnifiedToolResult(
                stage="cosim",
                status="cosim_fail",
                return_code=1,
                elapsed_seconds=0.1,
                summary="[cosim] cosim_fail",
                metrics={},
                artifacts={"tool_log": str(tmp / "missing.log")},
            )
            diagnosis = CoSimAnalyzer().analyze(context, result, LogNormalizer().normalize(result))

        self.assertEqual(diagnosis.category, "unknown")
        self.assertFalse(diagnosis.requires_structural_repair)

    def test_persistence_writes_cosim_diagnostics_and_artifact_index(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, _backend, _server = self.run_agent(tmp, output_root=tmp / "runs")
            run_dir = Path(result.run_directory)
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            decision = json.loads((run_dir / "cosim" / "decision.json").read_text(encoding="utf-8"))
            diagnosis = json.loads((run_dir / "cosim" / "diagnosis.json").read_text(encoding="utf-8"))
            artifacts = json.loads((run_dir / "cosim" / "artifact_index.json").read_text(encoding="utf-8"))
            baseline_diag = json.loads(
                (run_dir / "candidates" / "c000_baseline" / "cosim_diagnosis.json").read_text(encoding="utf-8")
            )
            transcript = json.loads((run_dir / "transcript" / "toolserver_transcript.json").read_text(encoding="utf-8"))
            final_kernel = (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8")
            artifact_paths_exist = all(Path(path).exists() for values in artifacts.values() for path in values)

        self.assertEqual(decision["should_run"], True)
        self.assertEqual(diagnosis["category"], "deadlock")
        self.assertEqual(baseline_diag["category"], "deadlock")
        self.assertTrue(artifacts["logs"])
        self.assertTrue(artifact_paths_exist)
        self.assertEqual([entry["kind"] for entry in transcript], ["csim", "synth", "cosim"])
        self.assertEqual(manifest["requires_structural_repair"], True)
        self.assertEqual(final_kernel, BASELINE_KERNEL)
        self.assertEqual(json.loads(json.dumps(manifest, sort_keys=True)), manifest)


@unittest.skipUnless(
    os.environ.get("FPT26_RUN_HLS_TESTS") == "1" and os.environ.get("FPT26_RUN_COSIM_TESTS") == "1",
    "set FPT26_RUN_HLS_TESTS=1 and FPT26_RUN_COSIM_TESTS=1 to run Vitis co-sim tests",
)
class CosimBaselineOfficialHlsTests(unittest.TestCase):
    def test_residual_stream_deadlock_baseline_cosim(self):
        from llm4hls.budget import Budget
        from llm4hls.harness import ToolServer
        from llm4hls.task import load_task

        task = load_task(Path("fpt26-harness/tasks/residual_stream_deadlock"))
        run_root = Path("fpt26-agent/runs/cosim_baseline_hls/residual_stream_deadlock/tools")
        output_root = Path("fpt26-agent/runs/cosim_baseline_hls/persist")
        server = ToolServer(task, Budget(task.budget), run_root)
        result = CompetitionAgent().run(task, server, output_root=output_root)
        run_dir = Path(result.run_directory)

        stages = [(stage.stage, stage.status) for stage in result.stage_results]
        self.assertEqual(stages[0][0], "csim")
        self.assertEqual(stages[1][0], "synth")
        self.assertIn(("cosim", result.stage_results[2].status), stages)
        self.assertEqual(result.cosim_decision.should_run, True)
        self.assertEqual((run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8"), task.kernel_code)
        self.assertTrue((run_dir / "cosim" / "artifact_index.json").is_file())
        self.assertEqual([entry.kind for entry in server.transcript], [stage for stage, _status in stages])

        cosim_result = next(stage for stage in result.stage_results if stage.stage == "cosim")
        if cosim_result.status != "pass":
            self.assertIsNotNone(result.cosim_diagnosis)
            self.assertTrue(result.cosim_diagnosis.evidence)
            joined = "\n".join(result.cosim_diagnosis.evidence).lower()
            self.assertRegex(joined, r"deadlock|stream|timeout|fifo|dataflow|channel|stall")
            if result.cosim_diagnosis.requires_structural_repair:
                self.assertEqual(result.initial_condition.condition, "structural_failure")


if __name__ == "__main__":
    unittest.main()
