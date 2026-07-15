"""Reference LLM4HLS agent: an iterative, budget-aware repair+optimize loop.

Workflow (correctness before PPA, exactly the competition's required order):
  1. csim the current kernel to establish state.
  2. while not correct: feed the compile/runtime log back to the LLM, get a new
     kernel, csim it -- until it passes or budget/rounds run out.
  3. once correct: synth for a baseline PPA figure.
  4. optimization rounds: ask the LLM to lower latency (pragmas / restructuring);
     each candidate must still pass csim AND synth AND beat the best latency,
     else it is discarded. Stop on no-improvement, round cap, or budget.

The agent only ever emits kernel source; the harness owns headers + testbench.
"""

from __future__ import annotations

import re

from .budget import BudgetExceeded
from .harness import ToolServer
from .llm import LLMClient
from .task import Task
from .tools import ToolResult

_SYSTEM = """You are an expert FPGA/HLS engineer working with AMD Vitis 2025.2, \
targeting an Alveo U55C at 200 MHz (5 ns clock). You iteratively write and optimize \
synthesizable HLS C++ kernels. Rules:
- Output ONLY the full contents of the kernel .cpp file, inside a single ```cpp fenced block.
- Do NOT change the top-level function signature, the header, or the testbench.
- Keep the code functionally correct first; optimize for latency second.
- Prefer general HLS techniques (PIPELINE, UNROLL, ARRAY_PARTITION, DATAFLOW) over hacks."""

_CODE_RE = re.compile(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", re.DOTALL)


def _extract_code(text: str) -> str | None:
    blocks = _CODE_RE.findall(text)
    if blocks:
        return blocks[0].strip() + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped else None


def _lat(r: ToolResult) -> int | None:
    if r.report is None:
        return None
    return (
        r.report.latency_worst
        if r.report.latency_worst is not None
        else r.report.latency_avg
    )


class ReferenceAgent:
    def __init__(
        self,
        task: Task,
        server: ToolServer,
        llm: LLMClient,
        max_rounds: int = 6,
        verbose: bool = True,
    ) -> None:
        self.task = task
        self.server = server
        self.llm = llm
        self.max_rounds = max_rounds
        self.verbose = verbose

    # -- utilities ---------------------------------------------------------
    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  [agent] {msg}", flush=True)

    def _afford(self, kind: str) -> bool:
        return self.server.budget.can_afford(kind)

    def _header_text(self) -> str:
        return "\n".join(f"// {n}\n{c}" for n, c in self.task.headers.items())

    def _ask(self, instruction: str, code: str, feedback: str) -> str | None:
        user = (
            f"## Kernel specification\n{self.task.description}\n\n"
            f"## Fixed header(s) (read-only)\n```cpp\n{self._header_text()}\n```\n\n"
            f"## Current kernel: {self.task.kernel_name}\n```cpp\n{code}\n```\n\n"
            f"## Latest tool feedback\n{feedback}\n\n"
            f"## Your task\n{instruction}"
        )
        resp = self.llm.complete(_SYSTEM, user)
        return _extract_code(resp)

    # -- phases ------------------------------------------------------------
    def _verify_correctness(self, code: str) -> tuple[bool, ToolResult]:
        """csim (fast) plus, for structural tasks, cosim (RTL — catches deadlock
        / invalid streaming that C-simulation silently tolerates)."""
        r = self.server.csim(code)
        if not r.ok:
            return False, r
        if self.task.requires_cosim and self._afford("cosim"):
            cr = self.server.cosim(code)
            return cr.ok, cr
        return True, r

    def _reach_correctness(self, code: str) -> tuple[bool, str]:
        ok, r = self._verify_correctness(code)
        self._log(f"initial check: {r.brief()}")
        if ok:
            self._log("starting code already correct")
            return True, code
        for attempt in range(1, self.max_rounds + 1):
            if not self._afford("csim"):
                self._log("out of budget before correctness reached")
                return False, code
            instr = (
                "The design is INCORRECT. If C-simulation failed, fix the functional "
                "bug from the log. If C-simulation PASSED but co-simulation DEADLOCKED "
                "or mismatched, this is a structural/streaming bug — e.g. a DATAFLOW "
                "stream written in a burst that bounded RTL FIFOs cannot buffer; "
                "restructure so producers and consumers stay rate-balanced. Return a "
                "corrected kernel."
            )
            new_code = self._ask(instr, code, self._feedback(r))
            if new_code is None:
                return False, code
            code = new_code
            ok, r = self._verify_correctness(code)
            self._log(f"repair attempt {attempt}: {r.brief()}")
            if ok:
                gate = "csim+cosim" if self.task.requires_cosim else "csim"
                self._log(f"correctness reached ({gate})")
                return True, code
        return False, code

    def _optimize(self, best: str, best_latency: int | None) -> str:
        rounds = 0
        while (
            rounds < self.max_rounds and self._afford("csim") and self._afford("synth")
        ):
            rounds += 1
            fb = f"Current design passes correctness. Best latency so far: {best_latency} cycles."
            instr = (
                "Optimize this correct kernel for LOWER latency on the target, while "
                "keeping it functionally correct and synthesizable. Apply HLS pragmas "
                "and/or restructure loops. Return the full optimized kernel."
            )
            cand = self._ask(instr, best, fb)
            if cand is None or cand.strip() == best.strip():
                self._log("no further optimization proposed; stopping")
                break
            cr = self.server.csim(cand)
            if not cr.ok:
                self._log(
                    f"opt round {rounds}: broke correctness ({cr.phase}); discard"
                )
                continue
            sr = self.server.synth(cand)
            if not sr.ok:
                self._log(f"opt round {rounds}: failed synth ({sr.phase}); discard")
                continue
            lat = _lat(sr)
            if best_latency is None or (lat is not None and lat < best_latency):
                self._log(
                    f"opt round {rounds}: latency {best_latency} -> {lat}; accept"
                )
                best, best_latency = cand, lat
            else:
                self._log(
                    f"opt round {rounds}: no improvement ({best_latency} -> {lat}); stop"
                )
                break
        return best

    def _feedback(self, r: ToolResult) -> str:
        return f"Tool result: {r.brief()}\n--- log (tail) ---\n{r.log[-3000:]}"

    # -- main --------------------------------------------------------------
    def run(self) -> str:
        t = self.task
        self._log(
            f"task={t.id} type={t.type} budget={self.server.budget.total} credits"
        )
        best = t.kernel_code
        try:
            correct, code = self._reach_correctness(best)
            if not correct:
                self._log("FAILED to reach correctness; returning last attempt")
                return code
            best = code  # cosim-verified already, for structural tasks
            verified = best
            best_latency = None
            if self._afford("synth"):
                r = self.server.synth(best)
                if r.ok:
                    best_latency = _lat(r)
                    self._log(f"baseline synth of correct design: {r.report.summary()}")
            best = self._optimize(best, best_latency)
            # If optimization changed a structural design, confirm it didn't
            # reintroduce a deadlock; revert to the verified version if it did.
            if (
                t.requires_cosim
                and best.strip() != verified.strip()
                and self._afford("cosim")
            ):
                cr = self.server.cosim(best)
                self._log(f"post-optimization RTL re-check: {cr.brief()}")
                if not cr.ok:
                    self._log(
                        "optimization reintroduced a structural hazard; reverting"
                    )
                    best = verified
        except BudgetExceeded as e:
            self._log(f"budget exhausted: {e}")
        self._log("done")
        return best
