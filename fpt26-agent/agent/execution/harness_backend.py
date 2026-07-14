from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from llm4hls.budget import BudgetExceeded

from .result_adapter import UnifiedToolResult, adapt_tool_result, exception_result


class HarnessBackend:
    """Small adapter over the official metered ToolServer interface."""

    def __init__(self, task: Any, tool_server: Any) -> None:
        self.task = task
        self.tool_server = tool_server
        self.tool_server.run_root = Path(self.tool_server.run_root).resolve()
        self.tool_server.run_root.mkdir(parents=True, exist_ok=True)

    @property
    def run_root(self) -> Path:
        return Path(self.tool_server.run_root)

    def csim(self, kernel_code: str) -> UnifiedToolResult:
        return self._invoke("csim", self.tool_server.csim, kernel_code)

    def synth(self, kernel_code: str) -> UnifiedToolResult:
        return self._invoke("synth", self.tool_server.synth, kernel_code)

    def cosim(self, kernel_code: str) -> UnifiedToolResult:
        return self._invoke("cosim", self.tool_server.cosim, kernel_code)

    def _invoke(
        self,
        stage: str,
        method: Callable[[str], Any],
        kernel_code: str,
    ) -> UnifiedToolResult:
        budget_before = self._budget_spent()
        artifacts = self._expected_artifacts(stage)
        try:
            tool_result = method(kernel_code)
        except BudgetExceeded as exc:
            self._write_text_log(artifacts, f"{type(exc).__name__}: {exc}\n")
            return exception_result(
                stage,
                "budget_exceeded",
                exc,
                artifacts=artifacts,
                budget_before=budget_before,
                budget_after=self._budget_spent(),
            )
        except TimeoutError as exc:
            self._write_text_log(artifacts, f"{type(exc).__name__}: {exc}\n")
            return exception_result(
                stage,
                "timeout",
                exc,
                artifacts=artifacts,
                budget_before=budget_before,
                budget_after=self._budget_spent(),
            )
        except Exception as exc:
            self._write_text_log(artifacts, f"{type(exc).__name__}: {exc}\n")
            return exception_result(
                stage,
                "exception",
                exc,
                artifacts=artifacts,
                budget_before=budget_before,
                budget_after=self._budget_spent(),
            )

        self._write_text_log(artifacts, getattr(tool_result, "log", ""))
        artifacts.update(self._actual_artifacts(stage, artifacts["run_dir"]))
        return adapt_tool_result(
            stage,
            tool_result,
            artifacts=artifacts,
            budget_before=budget_before,
            budget_after=self._budget_spent(),
        )

    def _budget_spent(self) -> int | None:
        budget = getattr(self.tool_server, "budget", None)
        spent = getattr(budget, "spent", None)
        return int(spent) if spent is not None else None

    def _next_call_number(self) -> int:
        current = getattr(self.tool_server, "_n", None)
        if isinstance(current, int):
            return current + 1
        transcript = getattr(self.tool_server, "transcript", None)
        if isinstance(transcript, list):
            return len(transcript) + 1
        return 1

    def _expected_artifacts(self, stage: str) -> dict[str, Any]:
        run_dir = self.run_root / f"{stage}_{self._next_call_number()}"
        return {"run_dir": str(run_dir.resolve())}

    def _write_text_log(self, artifacts: dict[str, Any], text: str) -> None:
        run_dir = Path(artifacts["run_dir"])
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "tool.log"
        log_path.write_text(text or "", encoding="utf-8")
        artifacts["tool_log"] = str(log_path.resolve())

    def _actual_artifacts(self, stage: str, run_dir_text: str) -> dict[str, Any]:
        run_dir = Path(run_dir_text)
        artifacts: dict[str, Any] = {}
        run_tcl = run_dir / "run_hls.tcl"
        if run_tcl.exists():
            artifacts["run_tcl"] = str(run_tcl)
        if stage == "synth":
            csynth_xml = run_dir / "synth_proj" / "sol" / "syn" / "report" / "csynth.xml"
            csynth_rpt = run_dir / "synth_proj" / "sol" / "syn" / "report" / "csynth.rpt"
            if csynth_xml.exists():
                artifacts["csynth_xml"] = str(csynth_xml)
            if csynth_rpt.exists():
                artifacts["csynth_rpt"] = str(csynth_rpt)
        if stage == "cosim":
            sol_dir = run_dir / "cosim_proj" / "sol"
            cosim_report = sol_dir / "sim" / "report"
            if cosim_report.exists():
                artifacts["cosim_report_dir"] = str(cosim_report)
            top = getattr(self.task, "top", None)
            if isinstance(top, str) and top:
                cosim_rpt = cosim_report / f"{top}_cosim.rpt"
                if cosim_rpt.exists():
                    artifacts["cosim_rpt"] = str(cosim_rpt)
            csynth_xml = sol_dir / "syn" / "report" / "csynth.xml"
            csynth_rpt = sol_dir / "syn" / "report" / "csynth.rpt"
            if csynth_xml.exists():
                artifacts["cosim_csynth_xml"] = str(csynth_xml)
            if csynth_rpt.exists():
                artifacts["cosim_csynth_rpt"] = str(csynth_rpt)
        return artifacts
