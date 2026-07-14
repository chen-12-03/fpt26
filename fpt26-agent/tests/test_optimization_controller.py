from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from agent.competition_agent import CompetitionAgent
from agent.core.candidate_store import CandidateStore
from agent.execution.result_adapter import UnifiedToolResult
from agent.input.task_adapter import TaskAdapter
from agent.strategy.optimization_controller import OptimizationController
from agent.transform.actions import TransformAction
from agent.transform.transformer import DeterministicTransformer


PART = "xcu55c-fsvh2892-2L-e"
BASELINE_KERNEL = """#include "kernel.h"
void top(int a[16], int b[16]) {
    for (int i = 0; i < 16; i++) {
        b[i] = a[i] + 1;
    }
}
"""
NO_LOOP_KERNEL = """#include "kernel.h"
void top(int a[16], int b[16]) {
    b[0] = a[0] + 1;
}
"""
PIPELINED_KERNEL = """#include "kernel.h"
void top(int a[16], int b[16]) {
    for (int i = 0; i < 16; i++) {
        #pragma HLS PIPELINE II=2
        b[i] = a[i] + 1;
    }
}
"""


class FakeBudget:
    def __init__(self, total: int = 40) -> None:
        self.total = total
        self.spent = 0
        self.cost = {"csim": 1, "synth": 4, "cosim": 8}
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
    def __init__(
        self,
        _task,
        tool_server,
        *,
        fail_pipeline_csim: bool = False,
        fail_pipeline_synth: bool = False,
        pipeline_metrics: dict | None = None,
        baseline_metrics: dict | None = None,
    ) -> None:
        self.tool_server = tool_server
        self.calls: list[str] = []
        self.kernel_inputs: list[str] = []
        self.fail_pipeline_csim = fail_pipeline_csim
        self.fail_pipeline_synth = fail_pipeline_synth
        self.pipeline_metrics = pipeline_metrics or metrics(latency=12, ii=1, clock=4.2, lut=130)
        self.baseline_metrics = baseline_metrics or metrics(latency=80, ii=4, clock=4.5, lut=100)

    def csim(self, kernel_code: str) -> UnifiedToolResult:
        self.calls.append("csim")
        self.kernel_inputs.append(kernel_code)
        if self.fail_pipeline_csim and "#pragma HLS PIPELINE" in kernel_code:
            return self._result("csim", "runtime_fail", {})
        return self._result("csim", "pass", {})

    def synth(self, kernel_code: str) -> UnifiedToolResult:
        self.calls.append("synth")
        self.kernel_inputs.append(kernel_code)
        if self.fail_pipeline_synth and "#pragma HLS PIPELINE" in kernel_code:
            return self._result("synth", "synth_error", {})
        result_metrics = self.pipeline_metrics if "#pragma HLS PIPELINE" in kernel_code else self.baseline_metrics
        return self._result("synth", "pass", result_metrics)

    def cosim(self, kernel_code: str) -> UnifiedToolResult:
        self.calls.append("cosim")
        self.kernel_inputs.append(kernel_code)
        return self._result("cosim", "pass", {})

    def _result(self, stage: str, status: str, result_metrics: dict) -> UnifiedToolResult:
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
        return UnifiedToolResult(
            stage=stage,
            status=status,
            return_code=0 if status == "pass" else 1,
            elapsed_seconds=0.1,
            summary=f"[{stage}] {status}",
            metrics=result_metrics,
            artifacts={},
            budget_before=0,
            budget_after=self.tool_server.budget.spent,
        )


def metrics(*, latency: int, ii: int, clock: float, lut: int = 100, ff: int = 50) -> dict:
    return {
        "estimated_clock_ns": clock,
        "latency_min": latency,
        "latency_max": latency,
        "ii_min": ii,
        "ii_max": ii,
        "lut": lut,
        "ff": ff,
        "dsp": 0,
        "bram": 0,
        "uram": 0,
    }


def make_task(tmp: Path, *, task_type: str = "optimize", kernel: str = BASELINE_KERNEL):
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "kernel.cpp").write_text(kernel, encoding="utf-8")
    (tmp / "kernel.h").write_text("void top(int a[16], int b[16]);\n", encoding="utf-8")
    (tmp / "tb.cpp").write_text("int main(){int a[16]={0}; int b[16]={0}; top(a,b); return 0;}\n", encoding="utf-8")
    return SimpleNamespace(
        dir=tmp,
        id="unit_optimize",
        type=task_type,
        difficulty=1,
        top="top",
        budget=40,
        part=PART,
        clock_ns=5.0,
        requires_cosim=False,
        initial_condition="",
        description="Optimize a simple loop.",
        kernel_name="kernel.cpp",
        kernel_code=kernel,
        headers={"kernel.h": "void top(int a[16], int b[16]);\n"},
        public_tb_name="tb.cpp",
        public_tb_code="int main(){int a[16]={0}; int b[16]={0}; top(a,b); return 0;}\n",
    )


class OptimizationControllerFakeTests(unittest.TestCase):
    def run_agent(
        self,
        tmp: Path,
        *,
        task_type: str = "optimize",
        kernel: str = BASELINE_KERNEL,
        total_budget: int = 40,
        output_root: Path | None = None,
        optimize_enabled: bool = True,
        max_candidates: int = 1,
        **backend_kwargs,
    ):
        backends: list[FakeBackend] = []

        def factory(task, server):
            backend = FakeBackend(task, server, **backend_kwargs)
            backends.append(backend)
            return backend

        task = make_task(tmp / "task", task_type=task_type, kernel=kernel)
        server = FakeToolServer(total_budget)
        result = CompetitionAgent(
            backend_factory=factory,
            optimize_enabled=optimize_enabled,
            max_optimization_candidates=max_candidates,
        ).run(task, server, output_root=output_root)
        return result, backends[0], server

    def test_pipeline_candidate_improves_and_is_selected(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, backend, _server = self.run_agent(Path(tmp_name))

        self.assertEqual(backend.calls, ["csim", "synth", "csim", "synth"])
        self.assertEqual(result.optimization_status, "improved")
        self.assertEqual(result.selected_candidate_id, "c001_pipeline_01")
        self.assertIn("#pragma HLS PIPELINE II=1", result.final_kernel)
        self.assertLess(result.final_metrics["latency_max"], result.baseline_metrics["latency_max"])

    def test_candidate_csim_failure_does_not_run_synth(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, backend, _server = self.run_agent(Path(tmp_name), fail_pipeline_csim=True)

        self.assertEqual(backend.calls, ["csim", "synth", "csim"])
        self.assertEqual(result.optimization_status, "no_improvement")
        self.assertEqual(result.selected_candidate_id, "c000_baseline")
        self.assertEqual(result.final_kernel, BASELINE_KERNEL)

    def test_synth_failure_candidate_is_not_selected(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, backend, _server = self.run_agent(Path(tmp_name), fail_pipeline_synth=True)

        self.assertEqual(backend.calls, ["csim", "synth", "csim", "synth"])
        self.assertEqual(result.optimization_status, "no_improvement")
        self.assertEqual(result.optimization_candidates[0].status, "synth_failed")

    def test_timing_failure_is_not_selected(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, _backend, _server = self.run_agent(
                Path(tmp_name),
                pipeline_metrics=metrics(latency=12, ii=1, clock=6.0, lut=130),
            )

        self.assertEqual(result.optimization_status, "no_improvement")
        self.assertFalse(result.optimization_candidates[0].constraint_checks["timing_valid"])
        self.assertEqual(result.selected_candidate_id, "c000_baseline")

    def test_resource_limit_failure_is_not_selected(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            task = make_task(tmp / "task")
            context = TaskAdapter.from_official_task(task)
            context = replace(context, resource_limits={"max_lut": 120})
            server = FakeToolServer()
            backend = FakeBackend(None, server, pipeline_metrics=metrics(latency=12, ii=1, clock=4.2, lut=130))
            baseline = [backend.csim(BASELINE_KERNEL), backend.synth(BASELINE_KERNEL)]
            store = CandidateStore(tmp / "runs")
            baseline_candidate = store.baseline_candidate(context, BASELINE_KERNEL)

            result = OptimizationController().optimize(
                context,
                baseline_candidate,
                baseline,
                backend,
                store,
                max_candidates=1,
            )

        self.assertEqual(result.status, "no_improvement")
        self.assertFalse(result.candidates[0].constraint_checks["resource_limits_valid"])
        self.assertEqual(result.selected_candidate.candidate_id, "c000_baseline")

    def test_no_improvement_falls_back_to_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, _backend, _server = self.run_agent(
                Path(tmp_name),
                pipeline_metrics=metrics(latency=80, ii=4, clock=4.5, lut=80),
            )

        self.assertEqual(result.optimization_status, "no_improvement")
        self.assertEqual(result.selected_candidate_id, "c000_baseline")
        self.assertEqual(result.selection_reason, "no_candidate_strictly_improved_key_ppa_metric")

    def test_budget_insufficient_stops_before_candidate_hls(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, backend, _server = self.run_agent(Path(tmp_name), total_budget=5)

        self.assertEqual(backend.calls, ["csim", "synth"])
        self.assertEqual(result.optimization_status, "hls_budget_insufficient")
        self.assertEqual(result.selected_candidate_id, "c000_baseline")

    def test_no_transformable_loop_returns_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, backend, _server = self.run_agent(
                Path(tmp_name),
                kernel=NO_LOOP_KERNEL,
                baseline_metrics=metrics(latency=80, ii=1, clock=4.5),
                pipeline_metrics=metrics(latency=12, ii=1, clock=4.2),
            )

        self.assertEqual(backend.calls, ["csim", "synth"])
        self.assertEqual(result.optimization_status, "no_safe_transform_action")
        self.assertEqual(result.optimization_candidates, [])

    def test_duplicate_or_conflicting_pragma_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            task = make_task(Path(tmp_name) / "task", kernel=PIPELINED_KERNEL)
            context = TaskAdapter.from_official_task(task)
            transformer = DeterministicTransformer()
            loop = transformer.discover_loops(PIPELINED_KERNEL)[0]
            duplicate = transformer.apply(context, PIPELINED_KERNEL, TransformAction("pipeline_loop", loop.target, ii=2))
            conflict = transformer.apply(context, PIPELINED_KERNEL, TransformAction("pipeline_loop", loop.target, ii=1))

        self.assertFalse(duplicate.ok)
        self.assertIn("equivalent", duplicate.error)
        self.assertFalse(conflict.ok)
        self.assertIn("conflicting", conflict.error)

    def test_top_signature_lineage_diff_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            result, _backend, _server = self.run_agent(tmp, output_root=tmp / "runs")
            run_dir = Path(result.run_directory)
            candidate_dir = run_dir / "candidates" / "c001_pipeline_01"
            manifest = json.loads((candidate_dir / "manifest.json").read_text(encoding="utf-8"))
            diff_text = (candidate_dir / "diff.patch").read_text(encoding="utf-8")
            search_summary = json.loads((run_dir / "optimization" / "search_summary.json").read_text(encoding="utf-8"))
            final_kernel = (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8")

        self.assertEqual(manifest["parent_candidate_id"], "c000_baseline")
        self.assertEqual(manifest["lineage"], ["c000_baseline"])
        self.assertEqual(manifest["validation_result"]["status"], "pass")
        self.assertIn("#pragma HLS PIPELINE II=1", diff_text)
        self.assertEqual(final_kernel, result.final_kernel)
        self.assertEqual(search_summary["optimization_status"], "improved")

    def test_optimize_disabled_and_repair_task_do_not_generate_candidates(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            disabled, backend_disabled, _server = self.run_agent(Path(tmp_name), optimize_enabled=False)
        with tempfile.TemporaryDirectory() as tmp_name:
            repair, backend_repair, _server = self.run_agent(Path(tmp_name), task_type="repair")

        self.assertEqual(backend_disabled.calls, ["csim", "synth"])
        self.assertEqual(disabled.optimization_status, "not_attempted")
        self.assertEqual(disabled.optimization_candidates, [])
        self.assertEqual(backend_repair.calls, ["csim", "synth"])
        self.assertEqual(repair.optimization_status, "task_type_not_optimizable")
        self.assertEqual(repair.optimization_candidates, [])

    def test_json_round_trip_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            result, _backend, _server = self.run_agent(Path(tmp_name))

        first = json.dumps(result.to_dict(), sort_keys=True)
        second = json.dumps(json.loads(result.to_json()), sort_keys=True)
        self.assertEqual(first, second)


@unittest.skipUnless(os.environ.get("FPT26_RUN_HLS_TESTS") == "1", "set FPT26_RUN_HLS_TESTS=1 to run Vitis HLS tests")
class OptimizationControllerOfficialHlsTests(unittest.TestCase):
    def test_dot_product_optimize_report_driven_loop(self):
        from llm4hls.budget import Budget
        from llm4hls.harness import ToolServer
        from llm4hls.task import load_task

        task = load_task(Path("fpt26-harness/tasks/dotProduct_optimize"))
        run_root = Path("fpt26-agent/runs/optimization_controller_hls/dotProduct_optimize/tools")
        output_root = Path("fpt26-agent/runs/optimization_controller_hls/persist")
        server = ToolServer(task, Budget(task.budget), run_root)
        result = CompetitionAgent(optimize_enabled=True, max_optimization_candidates=3).run(
            task,
            server,
            output_root=output_root,
        )
        run_dir = Path(result.run_directory)

        self.assertEqual(result.initial_condition.condition, "correct_unoptimized")
        self.assertEqual(result.optimization_status, "improved")
        self.assertNotEqual(result.selected_candidate_id, "c000_baseline")
        self.assertTrue(any(candidate.status == "synth_pass" for candidate in result.optimization_candidates))
        self.assertLess(
            result.final_metrics["latency_max"],
            result.baseline_metrics["latency_max"],
        )
        self.assertTrue(result.final_metrics["estimated_clock_ns"] <= min(task.clock_ns, 10.0))
        selected_dir = run_dir / "candidates" / result.selected_candidate_id
        self.assertTrue((selected_dir / "diff.patch").is_file())
        self.assertEqual((run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8"), result.final_kernel)


if __name__ == "__main__":
    unittest.main()
