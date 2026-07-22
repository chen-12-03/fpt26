# =============================================================================
# FPT26 Track-A Agent v3 — 公共数据模型 (Data Models)
# =============================================================================
# 【功能概述】
#   本文件定义了系统中所有跨模块/跨进程边界的公共数据结构。
#   这些模型是可序列化的，携带显式的 schema 版本号，
#   并且区分"未知/不适用"和数值 0。
#
# 【这是你应该看的第 3 个文件】
#   理解这些数据结构后，再看流水线和 Agent 代码会非常顺畅。
#
# 【设计原则】
#   1. 每个模型都支持 to_dict() 和 from_dict() 方法实现序列化/反序列化
#   2. 使用 frozen=True dataclass 确保不可变性（线程安全，可哈希）
#   3. 区分 None（未运行/不适用）和 False（运行但失败）
#
# 【核心模型层次】
#   RunStatus / GateResult          — 枚举（状态词汇表）
#   InterfaceGateEvidence           — 接口门控证据
#   FrequencyGateEvidence           — 频率门控证据（≥100MHz）
#   ResourceGateEvidence            — 资源门控证据（不超器件容量）
#   CoSimGateEvidence               — CoSim 门控证据
#   CandidateEvaluation             — 候选代码的完整门控评估
#   SubmissionEvidence              — 从 Submission 到 Evaluator 的证据
#   AnchorEvidence                  — 评分锚点的门控证据
#   EvaluationAccounting            — 成本/时间计账（评分的权威来源）
#   ArtifactManifest                — 工件清单（不可变记录）
#   ErrorRecord                     — 基础设施错误记录
# =============================================================================

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from agent.errors import DigestMismatchError, EvidenceError, MissingEvidenceError


# ═══════════════════════════════════════════════════════════════════════════════
# 状态词汇表（Status Vocabulary）
# ═══════════════════════════════════════════════════════════════════════════════

class RunStatus(str, Enum):
    """
    规范的终止状态枚举。

    RUNNING 仅在流水线执行过程中有效，不应出现在报告文件中。
    终端状态:
    - COMPLETED:            成功完成
    - FAILED:               流水线失败（如 CSim 未通过）
    - BUDGET_EXCEEDED:      credits 预算耗尽
    - INFRASTRUCTURE_ERROR: 基础设施错误（如 LLM 连接失败）
    """
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class GateResult(str, Enum):
    """门控检查结果的枚举。"""
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    NOT_RUN = "not_run"


# ═══════════════════════════════════════════════════════════════════════════════
# 门控证据（Gate Evidence — 确定性的检查结果）
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class InterfaceGateEvidence:
    """
    确定性公共接口/源代码契约门控的证据。

    检查项:
    - 函数签名是否保持不变
    - 必需的 #include 是否保留
    - 括号是否平衡
    - 是否嵌入了禁止的内容（如 hidden_tb 引用）
    """
    ok: bool
    reason: str | None = None
    fingerprint: str | None = None              # 接口指纹（SHA256）
    canonical_signature: str | None = None      # 规范化函数签名
    required_includes_present: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "reason": self.reason,
            "fingerprint": self.fingerprint,
            "canonical_signature": self.canonical_signature,
            "required_includes_present": self.required_includes_present,
        }


@dataclass(frozen=True)
class FrequencyGateEvidence:
    """
    强制 100MHz 时序门控的证据。

    公式: 频率(MHz) = 1000 / clock_period_ns
    要求: clock_period_ns ≤ 10.0（即频率 ≥ 100 MHz）
    """
    ok: bool
    reason: str | None = None
    target_clock_ns: float | None = None        # 目标时钟周期（默认 10.0ns）
    candidate_clock_ns: float | None = None     # 候选设计的时钟周期
    frequency_mhz: float | None = None           # 计算出的频率
    minimum_frequency_mhz: float = 100.0         # 最低频率要求

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "reason": self.reason,
            "target_clock_ns": self.target_clock_ns,
            "candidate_clock_ns": self.candidate_clock_ns,
            "frequency_mhz": self.frequency_mhz,
            "minimum_frequency_mhz": self.minimum_frequency_mhz,
        }


@dataclass(frozen=True)
class ResourceGateEvidence:
    """
    器件容量门控的证据。

    检查 LUT, FF, DSP, BRAM_18K, URAM 五种资源的使用量
    是否不超过目标器件 (Alveo U55C) 的可用量。
    """
    ok: bool
    reason: str | None = None
    resources: dict[str, int] = field(default_factory=dict)   # 使用的资源
    available: dict[str, int] = field(default_factory=dict)   # 可用的资源

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "reason": self.reason,
            "resources": dict(self.resources),
            "available": dict(self.available),
        }


@dataclass(frozen=True)
class CoSimGateEvidence:
    """
    强制 C/RTL 联合仿真门控的证据。

    仅对结构型任务（有 streaming/dataflow）需要。
    CoSim 使用深度为 2 的有界 FIFO（CSim 使用无界 FIFO）。
    """
    ok: bool
    phase: str | None = None
    source_sha256: str | None = None
    latency_min: int | None = None
    latency_avg: int | None = None
    latency_max: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "phase": self.phase,
            "source_sha256": self.source_sha256,
            "latency_min": self.latency_min,
            "latency_avg": self.latency_avg,
            "latency_max": self.latency_max,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 候选代码评估（Candidate Evaluation）
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CandidateEvaluation:
    """
    一个候选内核的完整公共门控评估。

    包含从接口门控到 CoSim 门控的所有检查结果。
    每个 Agent 在验证新代码时都会产生一个 CandidateEvaluation。
    """
    source_sha256: str                                   # 候选源码的 SHA256 摘要
    interface: InterfaceGateEvidence = field(
        default_factory=lambda: InterfaceGateEvidence(ok=False)
    )
    csim: GateResult = GateResult.NOT_RUN
    synth: GateResult = GateResult.NOT_RUN
    frequency: FrequencyGateEvidence | None = None
    resource: ResourceGateEvidence | None = None
    cosim: CoSimGateEvidence | None = None
    stage: str = ""                                      # 产生此评估的流水线阶段
    accepted: bool = False                                # 是否通过所有门控
    failure_reason: str = ""                              # 失败原因（如果未通过）
    elapsed_s: float = 0.0                                # 验证耗时（秒）
    # Synth PPA（综合通过时填充）
    synth_latency: int | None = None                      # 延迟（时钟周期）
    synth_ii: int | None = None                           # 启动间隔（II）
    synth_clock_ns: float | None = None                   # 时钟周期（ns）
    synth_resources: dict[str, int] = field(default_factory=dict)  # 资源使用

    def fail(self, reason: str) -> None:
        """标记评估为失败。"""
        self.accepted = False
        self.failure_reason = reason

    def to_dict(self) -> dict[str, Any]:
        csim_val = self.csim.value if isinstance(self.csim, GateResult) else self.csim
        synth_val = self.synth.value if isinstance(self.synth, GateResult) else self.synth
        return {
            "source_sha256": self.source_sha256,
            "interface": self.interface.to_dict(),
            "csim": csim_val, "synth": synth_val,
            "frequency": self.frequency.to_dict() if self.frequency else None,
            "resource": self.resource.to_dict() if self.resource else None,
            "cosim": self.cosim.to_dict() if self.cosim else None,
            "stage": self.stage, "accepted": self.accepted,
            "failure_reason": self.failure_reason, "elapsed_s": self.elapsed_s,
            "synth_latency": self.synth_latency, "synth_ii": self.synth_ii,
            "synth_clock_ns": self.synth_clock_ns,
            "synth_resources": dict(self.synth_resources),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SubmissionEvidence — 跨 Submission → Evaluator 边界的证据
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SubmissionEvidence:
    """
    Submission 运行的完整可序列化证据。

    Evaluator 读取此证据来验证提交的内核确实是由合法的 Submission 运行产生的，
    并继承成本计账信息。

    关键字段:
    - kernel_sha256: 内核代码的 SHA256（Evaluator 用它验证文件完整性）
    - credits_spent/total: credits 消耗（Evaluator 继承此信息）
    - 各门控的 OK 状态（Evaluator 不会重新运行公共门控）
    """
    schema_version: int = 1
    run_id: str = ""
    task_id: str = ""

    # 状态
    status: str = RunStatus.RUNNING.value

    # 内核身份
    kernel_sha256: str = ""

    # 成本计账（Evaluator 继承，不会重置为 0）
    credits_spent: int = 0
    credits_total: int = 0

    # LLM 使用
    model: str | None = None
    token_usage: dict[str, Any] | None = None

    # 时间
    submission_started_at: str = ""           # ISO 8601 UTC
    submission_wall_seconds: float = 0.0
    tool_wall_seconds: float = 0.0

    # 公共门控结果
    interface_ok: bool | None = None
    csim_ok: bool | None = None
    synth_ok: bool | None = None
    frequency_ok: bool | None = None
    resource_ok: bool | None = None
    cosim_ok: bool | None = None

    # 评分策略
    scoring_profile: str = "balanced"

    # 停止原因（completed 时为空）
    stop_reason: str = ""

    @classmethod
    def from_run_state(cls, state: Any, *, run_id: str = "") -> "SubmissionEvidence":
        """从终止的 RunState 构造证据。"""
        from datetime import datetime, timezone

        started = state.metadata.get("submission_started_at", "")
        if not started:
            started = datetime.now(timezone.utc).isoformat()

        kernel_text = getattr(state, "kernel", "") or ""
        kernel_sha256 = hashlib.sha256(kernel_text.encode("utf-8")).hexdigest()

        budget = getattr(getattr(state, "server", None), "budget", None)
        spent = getattr(budget, "spent", 0) if budget is not None else 0
        total = getattr(budget, "total", 0) if budget is not None else 0

        tool_wall = sum(
            getattr(r, "elapsed_s", 0.0) for r in getattr(state, "results", [])
        )

        llm_summary: dict[str, Any] | None = None
        llm = getattr(state, "llm", None)
        if llm is not None:
            token_usage = getattr(llm, "token_usage", None)
            snapshot = getattr(token_usage, "snapshot", None)
            llm_summary = {
                "model": getattr(llm, "model", None),
                "token_usage": snapshot() if callable(snapshot) else None,
            }

        return cls(
            schema_version=1, run_id=run_id,
            task_id=getattr(getattr(state, "task", None), "id", ""),
            status=state.status, kernel_sha256=kernel_sha256,
            credits_spent=spent, credits_total=total,
            model=llm_summary.get("model") if llm_summary else None,
            token_usage=llm_summary.get("token_usage") if llm_summary else None,
            submission_started_at=started,
            tool_wall_seconds=round(tool_wall, 3),
            interface_ok=getattr(state, "interface_ok", None),
            csim_ok=getattr(state, "csim_ok", None),
            synth_ok=getattr(state, "synth_ok", None),
            frequency_ok=getattr(state, "frequency_ok", None),
            resource_ok=getattr(state, "resource_ok", None),
            cosim_ok=getattr(state, "cosim_ok", None),
            scoring_profile=getattr(getattr(state, "config", None), "scoring_profile", "balanced"),
            stop_reason=getattr(state, "stop_reason", ""),
        )

    def validate_against_kernel(self, kernel_path: str) -> None:
        """
        验证内核摘要是否匹配。

        如果内核文件的 SHA256 与 evidence 中记录的不一致，
        抛出 DigestMismatchError。
        """
        actual = ArtifactManifest.from_path(kernel_path, role="kernel")
        if actual.sha256 != self.kernel_sha256:
            raise DigestMismatchError(
                f"kernel digest mismatch: evidence={self.kernel_sha256[:16]}… "
                f"actual={actual.sha256[:16]}…"
            )

    def require_completed(self) -> None:
        """如果 Submission 未达到终止通过状态，抛出异常。"""
        if self.status != RunStatus.COMPLETED.value:
            raise EvidenceError(
                f"submission did not complete (status={self.status}, "
                f"stop_reason={self.stop_reason})"
            )
        if not self.kernel_sha256:
            raise MissingEvidenceError("submission evidence is missing kernel digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id, "task_id": self.task_id,
            "status": self.status, "kernel_sha256": self.kernel_sha256,
            "credits_spent": self.credits_spent,
            "credits_total": self.credits_total,
            "model": self.model, "token_usage": self.token_usage,
            "submission_started_at": self.submission_started_at,
            "submission_wall_seconds": self.submission_wall_seconds,
            "tool_wall_seconds": self.tool_wall_seconds,
            "interface_ok": self.interface_ok,
            "csim_ok": self.csim_ok, "synth_ok": self.synth_ok,
            "frequency_ok": self.frequency_ok,
            "resource_ok": self.resource_ok,
            "cosim_ok": self.cosim_ok,
            "scoring_profile": self.scoring_profile,
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubmissionEvidence":
        """反序列化，容忍缺失的可选字段。"""
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            run_id=str(data.get("run_id", "")),
            task_id=str(data.get("task_id", "")),
            status=str(data.get("status", "running")),
            kernel_sha256=str(data.get("kernel_sha256", "")),
            credits_spent=int(data.get("credits_spent", 0)),
            credits_total=int(data.get("credits_total", 0)),
            model=data.get("model"),
            token_usage=data.get("token_usage"),
            submission_started_at=str(data.get("submission_started_at", "")),
            submission_wall_seconds=float(data.get("submission_wall_seconds", 0.0)),
            tool_wall_seconds=float(data.get("tool_wall_seconds", 0.0)),
            interface_ok=data.get("interface_ok"),
            csim_ok=data.get("csim_ok"), synth_ok=data.get("synth_ok"),
            frequency_ok=data.get("frequency_ok"),
            resource_ok=data.get("resource_ok"), cosim_ok=data.get("cosim_ok"),
            scoring_profile=str(data.get("scoring_profile", "balanced")),
            stop_reason=str(data.get("stop_reason", "")),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# EvaluationAccounting — 评分的成本/时间权威来源
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EvaluationAccounting:
    """
    评分评估的完整成本/时间计账。

    这是评分的**业务权威来源**。metadata 可能持有序列化镜像，
    但评分函数必须直接接收此对象 —— 永远不要从 metadata dict 读取成本/时间。
    """
    submission_credits: int
    evaluator_credits: int
    submission_wall_seconds: float
    evaluator_wall_seconds: float

    @property
    def total_credits(self) -> int:
        return self.submission_credits + self.evaluator_credits

    @property
    def total_wall_seconds(self) -> float:
        return self.submission_wall_seconds + self.evaluator_wall_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "submission_credits": self.submission_credits,
            "evaluator_credits": self.evaluator_credits,
            "total_credits": self.total_credits,
            "submission_wall_seconds": self.submission_wall_seconds,
            "evaluator_wall_seconds": self.evaluator_wall_seconds,
            "total_wall_seconds": self.total_wall_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationAccounting":
        return cls(
            submission_credits=int(data.get("submission_credits", 0)),
            evaluator_credits=int(data.get("evaluator_credits", 0)),
            submission_wall_seconds=float(data.get("submission_wall_seconds", 0.0)),
            evaluator_wall_seconds=float(data.get("evaluator_wall_seconds", 0.0)),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ArtifactManifest — 工件清单（不可变记录）
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ArtifactManifest:
    """已持久化工件的不可变记录。"""
    path: str
    sha256: str
    role: str = "unknown"           # "kernel" | "report" | "evidence"
    fully_verified: bool = False
    fallback_starter_used: bool = False
    schema_version: int = 1

    @classmethod
    def from_path(cls, path: str, *, role: str = "kernel") -> "ArtifactManifest":
        """通过读取并哈希文件来创建清单。"""
        from pathlib import Path
        fp = Path(path)
        if not fp.is_file():
            raise FileNotFoundError(f"artifact not found: {path}")
        sha256 = hashlib.sha256(fp.read_bytes()).hexdigest()
        return cls(path=path, sha256=sha256, role=role)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "path": self.path, "sha256": self.sha256,
            "role": self.role, "fully_verified": self.fully_verified,
            "fallback_starter_used": self.fallback_starter_used,
        }
