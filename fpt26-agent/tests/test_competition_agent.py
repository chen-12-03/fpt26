from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent.competition_agent import CompetitionAgent
from agent.execution.result_adapter import UnifiedToolResult


PART = "xcu55c-fsvh2892-2L-e"


class FakeBudget:
    def __init__(self, total: int = 10) -> None:
        self.total = total
        self.spent = 0
        self.calls: list[SimpleNamespace] = []

    def remaining(self) -> int:
        return self.total - self.spent

    def charge(self, kind: str) -> None:
        cost = {"csim": 1, "synth": 4, "cosim": 8}.get(kind, 1)
        self.spent += cost
        self.calls.append(SimpleNamespace(kind=kind, cost=cost, spent_after=self.spent))


class FakeToolServer:
    def __init__(self) -> None:
        self.budget = FakeBudget()
        self.transcript: list[SimpleNamespace] = []


class FakeBackend:
    def __init__(
        self,
        task,
        tool_server,
        plan: dict[str, UnifiedToolResult],
    ) -> None:
        self.task = task
        self.tool_server = tool_server
        self.plan = plan
        self.calls: list[str] = []
        self.kernel_inputs: list[str] = []

    def csim(self, kernel_code: str) -> UnifiedToolResult:
        return self._run("csim", kernel_code)

    def synth(self, kernel_code: str) -> UnifiedToolResult:
        return self._run("synth", kernel_code)

    def cosim(self, kernel_code: str) -> UnifiedToolResult:
        return self._run("cosim", kernel_code)

    def _run(self, stage: str, kernel_code: str) -> UnifiedToolResult:
        self.calls.append(stage)
        self.kernel_inputs.append(kernel_code)
        result = self.plan.get(stage, make_result(stage, "pass"))
        if result.status != "budget_exceeded":
            self.tool_server.budget.charge(stage)
            self.tool_server.transcript.append(
                SimpleNamespace(
                    n=len(self.tool_server.transcript) + 1,
                    kind=stage,
                    phase=result.status,
                    spent=self.tool_server.budget.spent,
                    detail=result.summary,
                )
            )
        return result


def make_task(tmp: Path, *, task_type: str = "optimize", requires_cosim: bool = False, kernel: str = "int top(){return 0;}\n"):
    (tmp / "kernel.cpp").write_text(kernel, encoding="utf-8")
    (tmp / "kernel.h").write_text("int top();\n", encoding="utf-8")
    (tmp / "tb.cpp").write_text("int main(){return top();}\n", encoding="utf-8")
    return SimpleNamespace(
        dir=tmp,
        id="unit_task",
        type=task_type,
        difficulty=1,
        top="top",
        budget=10,
        part=PART,
        clock_ns=5.0,
        requires_cosim=requires_cosim,
        initial_condition="",
        description="unit",
        kernel_name="kernel.cpp",
        kernel_code=kernel,
        headers={"kernel.h": "int top();\n"},
        public_tb_name="tb.cpp",
        public_tb_code="int main(){return top();}\n",
    )


def make_result(stage: str, status: str, *, log_path: Path | None = None, summary: str | None = None) -> UnifiedToolResult:
    return UnifiedToolResult(
        stage=stage,
        status=status,
        return_code=0 if status == "pass" else 1,
        elapsed_seconds=0.1,
        summary=summary or f"[{stage}] {status}",
        metrics={},
        artifacts={"tool_log": str(log_path)} if log_path else {},
        budget_before=0,
        budget_after=1,
    )


def write_log(tmp: Path, text: str, name: str = "tool.log") -> Path:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return path


class CompetitionAgentUnitTests(unittest.TestCase):
    def run_agent(self, task, plan):
        instances: list[FakeBackend] = []

        def factory(task_obj, server_obj):
            backend = FakeBackend(task_obj, server_obj, plan)
            instances.append(backend)
            return backend

        server = FakeToolServer()
        result = CompetitionAgent(backend_factory=factory).run(task, server)
        return result, instances[0], server

    def test_csim_failure_stops_before_synth(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            task = make_task(tmp, task_type="repair")
            log_path = write_log(tmp, "Mismatch at index 0: expected 1 actual 2\n")
            result, backend, _server = self.run_agent(task, {"csim": make_result("csim", "runtime_fail", log_path=log_path)})

        self.assertEqual(backend.calls, ["csim"])
        self.assertEqual(result.initial_condition.condition, "csim_failure")
        self.assertEqual(result.status, "stopped")

    def test_synth_failure_stops_before_cosim(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            task = make_task(tmp, task_type="optimize", requires_cosim=True)
            log_path = write_log(tmp, "ERROR: [HLS 200-70] Synthesizability check failed\n")
            result, backend, _server = self.run_agent(task, {"synth": make_result("synth", "synth_error", log_path=log_path)})

        self.assertEqual(backend.calls, ["csim", "synth"])
        self.assertEqual(result.initial_condition.condition, "synth_failure")
        self.assertEqual(result.status, "stopped")

    def test_normal_call_order_and_correct_unoptimized(self):
        kernel = "int top(){return 42;}\n"
        with tempfile.TemporaryDirectory() as tmp_name:
            task = make_task(Path(tmp_name), task_type="optimize", kernel=kernel)
            result, backend, server = self.run_agent(task, {})

        self.assertEqual(backend.calls, ["csim", "synth"])
        self.assertEqual(backend.kernel_inputs, [kernel, kernel])
        self.assertEqual(result.initial_condition.condition, "correct_unoptimized")
        self.assertEqual(result.final_kernel, kernel)
        self.assertEqual(result.budget["spent"], server.budget.spent)
        self.assertEqual([entry["kind"] for entry in result.budget["transcript"]], ["csim", "synth"])

    def test_structural_task_conditionally_runs_cosim(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            task = make_task(tmp, task_type="structural", requires_cosim=True)
            log_path = write_log(tmp, "Deadlock detected in DATAFLOW stream FIFO channel\n")
            result, backend, _server = self.run_agent(task, {"cosim": make_result("cosim", "cosim_fail", log_path=log_path)})

        self.assertEqual(backend.calls, ["csim", "synth", "cosim"])
        self.assertEqual(result.initial_condition.condition, "structural_failure")

    def test_budget_and_timeout_status_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            task = make_task(tmp)
            timeout_log = write_log(tmp, "tool timed out\n", "timeout.log")
            timeout, _backend, _server = self.run_agent(
                task,
                {"synth": make_result("synth", "timeout", log_path=timeout_log, summary="tool timed out")},
            )
            budget, _backend2, _server2 = self.run_agent(
                task,
                {"csim": make_result("csim", "budget_exceeded", summary="BudgetExceeded: no credits")},
            )

        self.assertEqual(timeout.status, "timeout")
        self.assertEqual(timeout.initial_condition.condition, "timeout")
        self.assertEqual(budget.status, "budget_exceeded")
        self.assertEqual(budget.initial_condition.condition, "budget_exceeded")

    def test_json_round_trip_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp_name:
            task = make_task(Path(tmp_name))
            result, _backend, _server = self.run_agent(task, {})

        first = json.dumps(result.to_dict(), sort_keys=True)
        second = json.dumps(json.loads(result.to_json()), sort_keys=True)
        self.assertEqual(first, second)


@unittest.skipUnless(os.environ.get("FPT26_RUN_HLS_TESTS") == "1", "set FPT26_RUN_HLS_TESTS=1 to run Vitis HLS tests")
class CompetitionAgentOfficialHlsTests(unittest.TestCase):
    def run_official(self, task_name: str):
        from llm4hls.budget import Budget
        from llm4hls.harness import ToolServer
        from llm4hls.task import load_task

        task = load_task(Path("fpt26-harness/tasks") / task_name)
        run_root = Path("fpt26-agent/runs/competition_agent_tests") / task_name
        server = ToolServer(task, Budget(task.budget), run_root)
        return CompetitionAgent().run(task, server)

    def test_dot_product_optimize_csim_synth(self):
        result = self.run_official("dotProduct_optimize")
        self.assertEqual([stage.stage for stage in result.stage_results], ["csim", "synth"])
        self.assertTrue(all(stage.status == "pass" for stage in result.stage_results))
        self.assertEqual(result.initial_condition.condition, "correct_unoptimized")

    def test_projection_bugfix_initial_csim_failure(self):
        result = self.run_official("projection_bugfix")
        self.assertEqual([stage.stage for stage in result.stage_results], ["csim"])
        self.assertEqual(result.initial_condition.condition, "csim_failure")


if __name__ == "__main__":
    unittest.main()
