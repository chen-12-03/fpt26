# =============================================================================
# FPT26 Track-A Agent v3 — 工具边界层 (Harness Boundary)
# =============================================================================
# 【功能概述】
#   本文件是整个 Agent 系统与官方 llm4hls harness（工具框架）之间的**唯一边界**。
#   所有对 llm4hls 的导入都必须通过这个模块，禁止在 Agent 代码中直接 import llm4hls。
#
# 【这是你应该看的第 18 个文件】
#
# 【设计目的】
#   1. 单一依赖边界：如果 llm4hls API 发生变化，只需修改这个文件
#   2. 审计追踪：自动检测并记录 harness 的来源（路径和版本）
#   3. 测试隔离：可以在测试中替换为 mock 实现
#
# 【从这里导入的内容】
#   - Budget, BudgetExceeded: 预算管理（credits 消耗追踪）
#   - Task, load_task:       任务加载
#   - ToolResult:            工具调用结果
#   - HarnessCSimTool/CoSimTool/SynthTool: 底层工具实现（只读参考）
#   - HarnessToolServer:     官方 ToolServer 基类
#   - DEFAULT_PART/CLOCK_NS/FLOW_TARGET: 默认器件和时钟配置
#   - CREDIT_COST/CSIM_TIMEOUT_S/SYNTH_TIMEOUT_S/COSIM_TIMEOUT_S: 成本和超时配置
# =============================================================================

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════════
# Harness 来源追踪（延迟检测，在第一次调用时确定）
# ═══════════════════════════════════════════════════════════════════════════════

_provenance: dict[str, str] | None = None


def harness_provenance() -> dict[str, str]:
    """
    返回 {source, path} 用于审计日志。延迟检测。

    用于记录运行环境信息：llm4hls 的安装来源和路径。
    """
    global _provenance
    if _provenance is not None:
        return dict(_provenance)

    for mod_name in ("llm4hls",):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        f = getattr(mod, "__file__", None)
        if f:
            path = str(Path(f).resolve())
            source = "fpt26-agent-v3/llm4hls" if "fpt26-agent-v3" in path else path
            _provenance = {"source": source, "path": path}
            return dict(_provenance)

    _provenance = {"source": "unknown", "path": ""}
    return dict(_provenance)


# ═══════════════════════════════════════════════════════════════════════════════
# 通过单一边界重新导出 harness 类型
# ═══════════════════════════════════════════════════════════════════════════════

from llm4hls.budget import Budget, BudgetExceeded  # noqa: F401
# Budget:       管理 credits 消耗，追踪已使用量、剩余量
# BudgetExceeded: 预算耗尽时抛出的异常

from llm4hls.task import Task, load_task  # noqa: F401
# Task:       HLS 任务的数据结构（内核代码、测试平台、器件信息等）
# load_task:  从目录加载任务

from llm4hls.tools import (  # noqa: F401
    CoSimTool as HarnessCoSimTool,   # 底层 CoSim 实现（只读参考）
    CSimTool as HarnessCSimTool,     # 底层 CSim 实现（只读参考）
    SynthTool as HarnessSynthTool,   # 底层 Synth 实现（只读参考）
    ToolResult,                      # 工具调用结果（ok, log, report, elapsed_s 等）
)

from llm4hls.harness import ToolServer as HarnessToolServer  # noqa: F401
# HarnessToolServer: 官方 ToolServer 基类，我们的 ToolServer 继承它

from llm4hls.harness import ToolServer  # noqa: F401 — bare name for compat

from llm4hls.config import (  # noqa: F401
    DEFAULT_PART,        # 默认器件型号: "xcu55c-fsvh2892-2L-e" (Alveo U55C)
    DEFAULT_CLOCK_NS,    # 默认时钟周期: 10.0 ns (即 100 MHz)
    DEFAULT_FLOW_TARGET, # 默认流程目标: "vivado"
    CREDIT_COST,         # 各工具调用的 credit 消耗
    CSIM_TIMEOUT_S,      # CSim 超时: 300 秒
    SYNTH_TIMEOUT_S,     # Synth 超时: 1800 秒 (30 分钟)
    COSIM_TIMEOUT_S,     # CoSim 超时: 3600 秒 (60 分钟)
)
