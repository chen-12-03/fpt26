# =============================================================================
# FPT26 Track-A Agent v3 — 统一候选验证器 (Candidate Validator)
# =============================================================================
# 【功能概述】
#   本文件是**所有门控检查的唯一权威来源**。每个 Agent（Repair/Structural/Optimize）
#   和每个流水线阶段（Baseline/Evaluator）都必须使用这里导出的函数和类。
#   严禁在其他地方直接调用 CSim/Synth/CoSim 并自行判断门控逻辑。
#
# 【这是你应该看的第 11 个文件】
#   理解了门控系统，就理解了系统的"质量保证"层。
#
# 【门控检查链（Fail-Fast 模式）】
#
#   候选代码
#     │
#     ▼
#   ┌─────────────────────┐
#   │ 0. 接口门控 (免费)    │  ← 验证函数签名、include、括号平衡
#   │    Interface Gate    │     不消耗 credits，纯静态分析
#   └─────────┬───────────┘
#             │ pass
#             ▼
#   ┌─────────────────────┐
#   │ 1. CSim 门控         │  ← C 仿真功能验证
#   │    CSim Gate         │     消耗 ~1-2 credits
#   └─────────┬───────────┘
#             │ pass
#             ▼
#   ┌─────────────────────┐
#   │ 2. Synth 门控        │  ← C 综合（C++ → RTL）
#   │    Synthesis Gate    │     消耗 ~5-10 credits
#   └─────────┬───────────┘
#             │ pass
#             ▼
#   ┌─────────────────────┐
#   │ 3. 频率门控          │  ← 时钟频率 ≥ 100MHz？
#   │    Frequency Gate    │     period ≤ 10ns
#   └─────────┬───────────┘
#             │ pass
#             ▼
#   ┌─────────────────────┐
#   │ 4. 资源门控          │  ← LUT/FF/DSP/BRAM/URAM 不超出器件容量？
#   │    Resource Gate     │
#   └─────────┬───────────┘
#             │ pass
#             ▼
#   ┌─────────────────────┐
#   │ 5. CoSim 门控        │  ← C/RTL 联合仿真（仅结构型任务）
#   │    CoSim Gate        │     消耗 ~15-20 credits
#   └─────────┬───────────┘
#             │ pass
#             ▼
#   ✅ 标记为 "完全验证" (Fully Verified)
#
# 【关于 extract_code】
#   这个函数从 LLM 的回复中提取 C++ 代码。LLM 的输出格式要求是：
#   ```cpp
#   // ... kernel source code ...
#   ```
# =============================================================================

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from agent.errors import SecurityError
from agent.models import (
    CandidateEvaluation,
    CoSimGateEvidence,
    FrequencyGateEvidence,
    InterfaceGateEvidence,
    ResourceGateEvidence,
)
from scoring.scoring_v3 import check_capacity, verified_available_resources


# ═══════════════════════════════════════════════════════════════════════════════
# 代码提取工具（之前被复制在 4 个文件中，现已统一）
# ═══════════════════════════════════════════════════════════════════════════════

_CODE_RE = re.compile(r"```(?:cpp|c\+\+|c)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str | None:
    """
    从 LLM 响应中提取内核源代码（```cpp 围栏代码块）。

    LLM 被要求始终将代码放在 ```cpp ... ``` 围栏块中。
    如果没有找到围栏块，则将整个文本作为代码返回。

    返回:
        提取的 C++ 代码字符串，如果文本为空则返回 None
    """
    blocks = _CODE_RE.findall(text)
    if blocks:
        return blocks[0].strip() + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped else None


# ═══════════════════════════════════════════════════════════════════════════════
# 接口契约（Interface Contract）—— 确定性源代码验证
# ═══════════════════════════════════════════════════════════════════════════════
# 接口门控的目的是确保 LLM 不会修改"公共接口"：
# - 顶层函数签名不能改变（函数名、参数列表、返回类型）
# - 必需的 #include 不能删除
# - 不能嵌入 hidden/reference 引用
# - 括号必须平衡
# ═══════════════════════════════════════════════════════════════════════════════

_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_INCLUDE_RE = re.compile(r"^\s*#\s*include\s*([<\"][^>\"]+[>\"])", re.MULTILINE)
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_FORBIDDEN_EMBED_RE = re.compile(
    r"\b(?:hidden|reference)\s*[/\\]|"
    r"(?:^|[\"'/\\])(?:hidden|reference)(?:[\"'/\\]|$)|"
    r"\bhidden_tb\b|\breference_code\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InterfaceContract:
    """
    不可变的公共源代码契约，从 stater 代码中提取。

    字段:
        top:                  顶层函数名
        canonical_signature:  规范化后的函数签名（去除了空格差异）
        required_includes:    必需的 #include 列表
        fingerprint:          契约的 SHA256 指纹（用于快速比较）
    """
    top: str
    canonical_signature: str
    required_includes: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "top": self.top,
            "canonical_signature": self.canonical_signature,
            "required_includes": list(self.required_includes),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class CandidateValidation:
    """
    候选代码对接口契约的验证结果。

    字段:
        ok:                       验证是否通过
        reason:                   通过/失败原因
        fingerprint:              候选代码的接口指纹
        canonical_signature:      候选代码的规范化签名
        required_includes_present: 所有必需的 include 是否都存在
    """
    ok: bool
    reason: str
    fingerprint: str | None
    canonical_signature: str | None
    required_includes_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "reason": self.reason,
            "fingerprint": self.fingerprint,
            "canonical_signature": self.canonical_signature,
            "required_includes_present": self.required_includes_present,
        }


@dataclass(frozen=True)
class FrequencyGate:
    """
    100MHz 时序门控结果。

    检查综合后的设计是否能在 100MHz（10ns 时钟周期）下运行。
    频率 = 1000 / clock_period_ns (MHz)
    """
    ok: bool
    reason: str
    target_clock_ns: float
    candidate_clock_ns: float | None
    frequency_mhz: float | None
    minimum_frequency_mhz: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "reason": self.reason,
            "target_clock_ns": self.target_clock_ns,
            "candidate_clock_ns": self.candidate_clock_ns,
            "frequency_mhz": self.frequency_mhz,
            "minimum_frequency_mhz": self.minimum_frequency_mhz,
        }


@dataclass(frozen=True)
class ResourceGate:
    """
    器件容量门控结果。

    检查综合后的设计使用的 LUT/FF/DSP/BRAM_18K/URAM 是否不超出器件可用量。
    """
    ok: bool
    reason: str
    resources: dict[str, int]
    available: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "reason": self.reason,
            "resources": dict(self.resources),
            "available": dict(self.available),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 接口验证器（InterfaceValidator）
# ═══════════════════════════════════════════════════════════════════════════════

class InterfaceValidator:
    """
    验证 LLM 候选代码是否保持了公共源代码契约。

    验证项目:
    1. 代码非空
    2. 不含 markdown 围栏标记
    3. 不含 forbidden 嵌入（如 hidden_tb 引用）
    4. 括号平衡（{} 和 ()）
    5. 顶层函数签名不变（函数名、参数列表）
    6. 必需的 #include 全部存在
    """

    def __init__(self, contract: InterfaceContract) -> None:
        self.contract = contract

    @classmethod
    def from_task(cls, task: Any) -> "InterfaceValidator":
        """从 Task 对象构建验证器。"""
        return cls.from_source(task.top, task.kernel_code)

    @classmethod
    def from_source(cls, top: str, starter_code: str) -> "InterfaceValidator":
        """
        从不可变的公共 starter 源代码构建契约。

        提取:
        - 顶层函数签名
        - 规范化签名（去除空格差异）
        - 必需的 #include 列表
        - 契约指纹
        """
        signature = _extract_signature(starter_code, top)
        if signature is None:
            raise ValueError(f"top function {top!r} not found in starter kernel")
        canonical = _canonical_signature(signature)
        includes = tuple(sorted(set(_INCLUDE_RE.findall(starter_code))))
        return cls(
            InterfaceContract(
                top=top,
                canonical_signature=canonical,
                required_includes=includes,
                fingerprint=_interface_fingerprint(top, canonical, includes),
            )
        )

    def validate(self, code: str) -> CandidateValidation:
        """检查代码是否符合接口契约。"""
        # 1. 非空检查
        if not isinstance(code, str) or not code.strip():
            return CandidateValidation(False, "empty_candidate", None, None, False)
        # 2. 围栏标记检查
        if "```" in code:
            return CandidateValidation(False, "markdown_fence_in_candidate", None, None, False)
        # 3. 禁止嵌入检查
        if _FORBIDDEN_EMBED_RE.search(code):
            return CandidateValidation(False, "hidden_or_reference_embedding", None, None, False)
        # 4. 括号平衡检查
        if not _balanced(code, "{", "}") or not _balanced(code, "(", ")"):
            return CandidateValidation(False, "unbalanced_cpp_delimiters", None, None, False)
        # 5. 函数签名检查
        signature = _extract_signature(code, self.contract.top)
        if signature is None:
            return CandidateValidation(False, "top_function_missing", None, None, False)
        canonical = _canonical_signature(signature)
        if canonical != self.contract.canonical_signature:
            return CandidateValidation(
                False, "top_interface_changed",
                _interface_fingerprint(self.contract.top, canonical,
                                       tuple(sorted(set(_INCLUDE_RE.findall(code))))),
                canonical, False,
            )
        # 6. Include 检查
        includes = tuple(sorted(set(_INCLUDE_RE.findall(code))))
        includes_ok = set(self.contract.required_includes).issubset(includes)
        if not includes_ok:
            return CandidateValidation(
                False, "required_include_removed",
                _interface_fingerprint(self.contract.top, canonical, includes),
                canonical, False,
            )

        fingerprint = _interface_fingerprint(self.contract.top, canonical, includes)
        return CandidateValidation(True, "passed", fingerprint, canonical, True)


# ═══════════════════════════════════════════════════════════════════════════════
# 统一候选验证器（CandidateValidator）
# ═══════════════════════════════════════════════════════════════════════════════

class CandidateValidator:
    """
    通过 ValidationPlan 验证候选内核代码。

    所有工具调用都通过注入的 tool_executor 进行。
    验证器拥有接口检查、频率/资源门控和 CoSim 验证的全部逻辑。

    这是**唯一**的 CandidateValidator —— 不要在其他地方创建新的。
    """

    def __init__(self, task: Any, starter_code: str, *, tool_executor: Any = None) -> None:
        self._task = task
        self._starter_code = starter_code
        self._tool = tool_executor
        # 从 starter 代码构建接口契约（只构建一次）
        self._interface = InterfaceValidator.from_source(task.top, starter_code)
        self._contract = self._interface.contract

    @classmethod
    def from_task(cls, task: Any) -> "CandidateValidator":
        """从 Task 对象的公共 starter 代码构建验证器。"""
        return cls(task, task.kernel_code)

    @property
    def contract(self) -> InterfaceContract:
        return self._contract

    def validate_interface(self, code: str) -> CandidateEvaluation:
        """仅检查接口/源代码契约（零工具调用，不消耗 credits）。"""
        result = self._interface.validate(code)
        ev = CandidateEvaluation(
            source_sha256=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        )
        ev.interface = InterfaceGateEvidence(
            ok=result.ok, reason=result.reason,
            fingerprint=result.fingerprint,
            canonical_signature=result.canonical_signature,
            required_includes_present=result.required_includes_present,
        )
        if not result.ok:
            ev.fail(result.reason or "interface")
        else:
            ev.accepted = True
        return ev

    def validate(
        self, code: str, *,
        plan: ValidationPlan = ValidationPlan.CSIM_SYNTH,
        build_dir: Path | None = None,
        stage: str = "candidate",
        state: Any = None,
    ) -> CandidateEvaluation:
        """
        运行 plan 要求的每个门控，返回结构化结果。

        当提供 state 时，结果也会记录到 RunState 中以保持向后兼容。

        门控顺序（Fail-Fast）:
        0. 接口门控  1. CSim   2. Synth   3. 频率   4. 资源   5. CoSim
        """
        import time
        _t0 = time.monotonic()

        source_sha = hashlib.sha256(code.encode("utf-8")).hexdigest()
        ev = CandidateEvaluation(source_sha256=source_sha, stage=stage)

        # 0. 接口门控（总是运行）
        iface = self._check_interface(code)
        ev.interface = iface
        if not iface.ok:
            ev.fail(iface.reason or "interface")
            if state is not None:
                _record_interface_into_state(state, stage, False, iface.reason)
            return ev

        # 1. CSim 门控
        if plan in (ValidationPlan.CSIM_ONLY, ValidationPlan.CSIM_SYNTH,
                     ValidationPlan.FULL, ValidationPlan.SCORING):
            csim_ok = self._run_csim(code, build_dir, stage)
            ev.csim = "pass" if csim_ok else "fail"
            if state is not None:
                state.csim_ok = csim_ok
            if not csim_ok:
                ev.fail("csim")
                return ev

        # 2. Synth + 频率 + 资源门控
        if plan in (ValidationPlan.CSIM_SYNTH, ValidationPlan.FULL, ValidationPlan.SCORING):
            synth_report = self._run_synth(code, build_dir, stage)
            if synth_report is None:
                ev.synth = "fail"
                ev.fail("synth")
                return ev
            ev.synth = "pass"

            # 频率门控: 检查 clock_period ≤ 10ns（即 ≥100MHz）
            ev.frequency = self._check_frequency(synth_report)
            if not ev.frequency.ok:
                ev.fail(ev.frequency.reason or "frequency")
                return ev

            # 资源门控: 检查 LUT/FF/DSP/BRAM/URAM 不超出器件容量
            ev.resource = self._check_resource(synth_report)
            if not ev.resource.ok:
                ev.fail(ev.resource.reason or "resource")
                return ev

            # 提取 PPA 信息
            ev.synth_latency = _latency_from_report(synth_report)
            ev.synth_ii = getattr(synth_report, "interval_max", None)
            ev.synth_clock_ns = getattr(synth_report, "clock_period_ns", None)
            ev.synth_resources = dict(getattr(synth_report, "resources", {}) or {})

        # 3. CoSim 门控（仅结构型任务）
        requires_cosim = getattr(self._task, "requires_cosim", False)
        if plan == ValidationPlan.FULL and requires_cosim:
            cosim_ok, cosim_report = self._run_cosim_full(code, build_dir, stage)
            ev.cosim = CoSimGateEvidence(
                ok=cosim_ok, source_sha256=source_sha,
                latency_max=getattr(cosim_report, "latency_max", None) if cosim_report else None,
            )
            if state is not None:
                state.cosim_ok = cosim_ok
            if not cosim_ok:
                ev.fail("cosim")
                return ev

        ev.accepted = True
        ev.elapsed_s = round(time.monotonic() - _t0, 3)
        if state is not None:
            _mark_fully_verified(state)
        return ev


# ═══════════════════════════════════════════════════════════════════════════════
# 门控函数（从 agent/validation.py 合并）
# ═══════════════════════════════════════════════════════════════════════════════

def frequency_gate(report: Any, target_clock_ns: float) -> FrequencyGate:
    """
    检查综合后的设计是否满足 ≥100MHz 的最低频率要求。

    频率 = 1000 / clock_period_ns
    要求: clock_period_ns ≤ 10.0（即 frequency ≥ 100 MHz）
    """
    value = getattr(report, "clock_period_ns", None) if report is not None else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return FrequencyGate(False, "candidate_clock_missing", target_clock_ns, None, None)
    period = float(value)
    if not math.isfinite(period) or period <= 0:
        return FrequencyGate(False, "candidate_clock_invalid", target_clock_ns, period, None)
    frequency = 1000.0 / period
    if period > 10.0:  # 10ns = 100MHz
        return FrequencyGate(False, "minimum_100mhz_not_met", target_clock_ns, period, frequency)
    return FrequencyGate(True, "passed", target_clock_ns, period, frequency)


def resource_gate(report: Any) -> ResourceGate:
    """
    检查综合后的设计是否在器件容量范围内。

    器件: Alveo U55C (xcu55c-fsvh2892-2L-e)
    """
    resources = dict(getattr(report, "resources", None) or {})
    available = verified_available_resources(
        getattr(report, "available", None) if report is not None else None
    )
    if not available:
        return ResourceGate(False, "resource_capacity_missing", resources, {})
    if not resources or not check_capacity(resources, available):
        return ResourceGate(False, "resource_capacity_exceeded", resources, available)
    return ResourceGate(True, "passed", resources, available)


# ═══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def _latency_from_report(report: Any) -> int | None:
    """从综合报告中提取最坏情况延迟（worst-case latency）。"""
    if report is None:
        return None
    return (
        report.latency_worst
        if getattr(report, "latency_worst", None) is not None
        else getattr(report, "latency_avg", None)
    )


def _mark_fully_verified(state: Any) -> None:
    """
    标记当前内核为"完全验证"。

    只有当所有门控都通过时才标记：
    interface_ok AND csim_ok AND synth_ok AND frequency_ok AND resource_ok
    AND (如果任务需要 cosim) cosim_ok
    """
    if (
        getattr(state, "interface_ok", False)
        and getattr(state, "csim_ok", False)
        and getattr(state, "synth_ok", False)
        and getattr(state, "frequency_ok", False)
        and getattr(state, "resource_ok", False)
        and (not getattr(getattr(state, "task", None), "requires_cosim", False)
             or getattr(state, "cosim_ok", False))
    ):
        state.last_verified_kernel = state.kernel
        if isinstance(getattr(state, "metadata", None), dict):
            state.metadata["last_verified_kernel_stage"] = "public_acceptance"
