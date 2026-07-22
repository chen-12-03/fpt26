# =============================================================================
# FPT26 Track-A Agent v3 — 基础类型定义 (Agent Base Types)
# =============================================================================
# 【功能概述】
#   本文件定义了流水线中传递的两个核心数据结构：
#   1. AgentConfig  — 流水线配置参数（模式、预算、尝试次数等）
#   2. RunState     — 流水线的共享可变状态（在每一步之间传递和修改）
#
#   此外还定义了 Agent 协议（Protocol），所有 Agent 类都必须实现 `run(ctx) -> RunState`。
#
# 【这是你应该看的第 4 个文件】
#   理解 RunState 的字段含义后，再看流水线代码会非常顺畅。
#
# 【设计原则】
#   RunState 是"唯一的生产级上下文"。PipelineContext（agent.pipeline.core）已被弃用。
#   所有业务逻辑必须读取 RunState 的显式字段，metadata dict 仅用于序列化镜像。
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent.integrations.harness import Task, ToolResult, ToolServer


# ===========================================================================
# Agent 协议 (Protocol)
# ===========================================================================

class Agent(Protocol):
    """
    流水线 Agent 的协议定义。

    每个 Agent 是一个独立的策略模块。要添加新 Agent:
    1. 实现 run(ctx) -> RunState 方法
    2. 在 workflow.build_pipeline() 中添加对应的 Step

    协议（Protocol）是 Python 的结构类型系统 —— 任何实现了 run 方法的类
    都自动满足 Agent 协议，无需显式继承。
    """

    def run(self, ctx: "RunState") -> "RunState": ...


# ===========================================================================
# AgentResult — Agent 的返回值
# ===========================================================================

@dataclass
class AgentResult:
    """
    单个 Agent 运行后的返回值（不是流水线本身的返回值）。

    字段:
        kernel:       代理产生（或保持）的内核代码
        status:       运行状态 (running/completed/failed)
        results:      此 Agent 产生的工具调用结果列表
        best_latency: 最佳延迟（时钟周期数）
    """
    kernel: str
    status: str = "running"
    results: list[ToolResult] = field(default_factory=list)
    best_latency: int | None = None


# ===========================================================================
# AgentConfig — 流水线配置
# ===========================================================================

@dataclass
class AgentConfig:
    """
    控制一次流水线运行的各种参数。

    字段:
        mode:                    运行模式
                                 - auto:       自动选择
                                 - baseline:   仅基线（不调用 LLM）
                                 - repair:     仅修复
                                 - optimize:   仅优化
                                 - structural: 仅结构修复
                                 - full:       全部阶段

        run_role:                运行角色 (submission | evaluator)

        competition:             竞争模式开关
                                 - False: 单一策略顺序尝试
                                 - True:  多条策略并行，选最优（消耗更多 credits）

        max_repair_attempts:     RepairAgent 的最大尝试次数（默认 3）
        max_optimization_rounds: OptimizeAgent 的最大迭代轮次（默认 5）
        max_structural_attempts: StructuralRepairAgent 的最大尝试次数（默认 3）

        output_root:             输出根目录
        score:                   是否执行评分（Submission 为 False，Evaluator 为 True）
        scoring_profile:         评分策略名称 (balanced | extreme_speed | extreme_speed_capped)
        verbose:                 是否输出详细日志
    """
    mode: str = "auto"
    run_role: str = "submission"
    competition: bool = False
    max_repair_attempts: int = 3
    max_optimization_rounds: int = 5
    max_structural_attempts: int = 3
    output_root: str = "runs"
    score: bool = False
    scoring_profile: str = "balanced"
    verbose: bool = True

    @property
    def needs_llm(self) -> bool:
        """判断当前模式是否需要 LLM。

        只有 baseline 模式不需要 LLM（它只运行 CSim 基线）。
        """
        return self.mode in {"auto", "repair", "optimize", "structural", "full"}


# ===========================================================================
# RunState — 流水线的共享可变状态（核心！）
# ===========================================================================

@dataclass
class RunState:
    """
    流水线步骤间传递的共享可变状态。

    每个步骤函数接收一个 RunState，修改所需的字段，然后返回它（或返回副本）。
    流水线按步骤列表的顺序依次执行。

    【重要】显式字段替代了旧的 ad-hoc metadata dict。
    业务逻辑 MUST 读取显式字段，metadata 仅作为序列化镜像存在。

    核心字段分类:
    ┌─────────────────┬──────────────────────────────────────────────┐
    │ 类别             │ 字段                                        │
    ├─────────────────┼──────────────────────────────────────────────┤
    │ 依赖注入         │ task, server, llm, config                   │
    │ 演化中的内核     │ kernel（随修复/优化而变化）                   │
    │ 工具结果         │ results（所有工具调用的历史记录）             │
    │ 门控状态         │ csim_ok, synth_ok, cosim_ok,               │
    │                  │ interface_ok, frequency_ok, resource_ok     │
    │ PPA 追踪         │ best_latency, best_synth_result,           │
    │                  │ last_verified_kernel, safe_fallback_kernel  │
    │ 评分配置         │ scorecard, ref_scorecard                   │
    │ 运行状态         │ status, stop_reason                        │
    └─────────────────┴──────────────────────────────────────────────┘
    """
    # ---- 依赖注入（由流水线启动时设置）----
    task: Task                        # HLS 任务对象（包含内核代码、测试平台、器件信息等）
    server: ToolServer                # 工具服务器（提供 csim/synth/cosim 方法）
    llm: Any                          # LLM 客户端（可能为 None，baseline 模式不需要）
    config: AgentConfig               # 运行配置

    # ---- 演化中的内核代码 ----
    kernel: str                       # 当前内核的 C++ 源代码（Agent 会修改它）

    # ---- 工具调用历史 ----
    results: list[ToolResult] = field(default_factory=list)

    # ---- 门控状态（每个门控是一个 bool 检查点）----
    # 门控的设计哲学是 "fail-fast"：任何一个门控失败，后续阶段都会跳过
    csim_ok: bool = False             # C 仿真是否通过
    synth_ok: bool = False            # C 综合是否通过
    cosim_ok: bool = False            # C/RTL 联合仿真是否通过
    interface_ok: bool = False        # 接口契约是否保持（函数签名、include 等不变）
    frequency_ok: bool = False        # 频率门控是否通过（≥100MHz）
    resource_ok: bool = False         # 资源门控是否通过（不超过器件容量）

    # ---- PPA（性能/功耗/面积）追踪 ----
    best_latency: int | None = None           # 最佳延迟（时钟周期）
    best_synth_result: Any = None             # 最佳综合结果
    last_verified_kernel: str | None = None   # 最后通过所有门控的内核代码
    safe_fallback_kernel: str | None = None   # 安全回退内核（失败时回退到这里）

    # ---- 评分 ----
    scorecard: Any = None              # 对 starter 锚点的评分卡
    ref_scorecard: Any = None          # 对 reference 锚点的评分卡

    # ---- 运行状态 ----
    status: str = "running"            # running | completed | failed | budget_exceeded | infrastructure_error
    stop_reason: str = ""              # 停止原因（如 "csim_failed", "repair_failed" 等）

    # ---- 结构化字段（从 metadata dict 迁移而来，只读业务逻辑请读这些字段）----

    # 计账：成本/时间的唯一权威来源
    evaluation_accounting: Any = None  # EvaluationAccounting | None

    # Anchor 证据：评分步骤记录一次
    anchor_evidence: Any = None        # AnchorEvidence | dict | None

    # 门控历史：结构化的记录，替代 ad-hoc metadata 列表
    interface_validations: list[dict[str, Any]] = field(default_factory=list)
    synth_gate_history: list[dict[str, Any]] = field(default_factory=list)
    cosim_gate_history: list[dict[str, Any]] = field(default_factory=list)

    # 预检结果：任务级别的预检数据（Vitis 版本、器件型号等）
    task_preflight: dict[str, Any] = field(default_factory=dict)

    # 基础设施错误：运行期间遇到的基础设施错误
    infrastructure_errors: list[dict[str, Any]] = field(default_factory=list)

    # 工件清单：已持久化工件的清单
    artifact_manifests: list[Any] = field(default_factory=list)

    # ---- 自由格式元数据（仅用于序列化/Agent 间通信）----
    # ⚠ 业务逻辑必须优先使用上面的显式字段！
    metadata: dict[str, Any] = field(default_factory=dict)

    # ---- 辅助方法 ----

    def log(self, msg: str) -> None:
        """输出日志（仅在 verbose 模式下）。

        Agent 和流水线阶段使用此方法输出状态信息，
        格式为 "[{mode}] message"。
        """
        if self.config.verbose:
            print(f"  [{self.config.mode}] {msg}", flush=True)
