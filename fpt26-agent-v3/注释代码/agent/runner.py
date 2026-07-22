# =============================================================================
# FPT26 Track-A Agent v3 — 工具服务器 (Tool Runner & Adapters)
# =============================================================================
# 【功能概述】
#   本文件是 Agent 与底层 HLS 工具链之间的适配层。它将三个 HLS 工具
#   （CSim、Synth、CoSim）封装为 Python 类，并委托给 SecureToolExecutor
#   进行安全的子进程执行。
#
# 【这是你应该看的第 15 个文件】
#
# 【安全架构】
#   所有工具调用都必须经过 SecureToolExecutor，它负责：
#   1. 路径验证（防止路径遍历攻击）
#   2. Tcl 注入防护（防止恶意 Tcl 脚本注入）
#   3. 子进程环境清理（移除 API key 等敏感环境变量）
#   4. 输出脱敏（编辑日志中的敏感内容）
#
# 【C++17 源码准备】
#   Vitis HLS 2025.2 不完全支持 C++17 的 register 关键字，
#   所以在传给工具之前需要从源码中移除。
# =============================================================================

from __future__ import annotations

import re
from pathlib import Path

from llm4hls import config
from agent.integrations.harness import HarnessToolServer
from agent.integrations.vitis import SecureToolExecutor, SourceTransformer

# register 关键字在 C++17 中已弃用，但旧代码可能仍在使用
# Vitis HLS 不完全支持，需要移除
_REGISTER_KW_RE = re.compile(r"\bregister\s+")


def _prepare_cpp17_sources(files: dict[str, str]) -> dict[str, str]:
    """
    准备 C++17 兼容的源码。

    主要处理：
    - 移除 register 关键字（C++17 中已弃用）
    """
    return {name: _REGISTER_KW_RE.sub("", content) for name, content in files.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# 三个工具适配器（CSimTool, SynthTool, CoSimTool）
# ═══════════════════════════════════════════════════════════════════════════════
# 每个适配器:
# 1. 接收 C++ 源码文件
# 2. 调用 _prepare_cpp17_sources 处理
# 3. 委托给 SecureToolExecutor 执行
# 4. 返回 ToolResult
# ═══════════════════════════════════════════════════════════════════════════════

class CSimTool:
    """
    C 仿真工具适配器。

    CSim（C Simulation）使用 C++ 编译器运行 HLS 内核，进行功能验证。
    它比 Synth 快得多（几秒 vs 几分钟），但不能验证可综合性。
    """

    def __init__(self, executor: SecureToolExecutor | None = None,
                 data_files: dict[str, bytes] | None = None,
                 *, workspace_root: str | Path = "/workspace") -> None:
        self._executor = executor or SecureToolExecutor(workspace_root=workspace_root)
        self.data_files = data_files

    def run(self, build_dir: Path, files: dict[str, str], top: str,
            part: str = config.DEFAULT_PART, clock_ns: float = config.DEFAULT_CLOCK_NS,
            data_files: dict[str, bytes] | None = None):
        """
        运行 C 仿真。

        参数:
            build_dir:  构建目录
            files:      源码文件字典 {文件名: 内容}
            top:        顶层函数名
            part:       目标器件型号
            clock_ns:   目标时钟周期（纳秒）
            data_files: 测试数据文件

        返回:
            ToolResult: 包含 ok（通过/失败）、log（日志）、elapsed_s（耗时）等字段
        """
        prepared = _prepare_cpp17_sources(files)
        fixtures = self.data_files if data_files is None else data_files
        return self._executor.csim(
            build_dir, prepared, top,
            part=part, clock_ns=clock_ns, data_files=fixtures,
        )


class SynthTool:
    """
    C 综合工具适配器。

    Synth（Synthesis/综合）调用 Vitis HLS 将 C++ 代码转化为 RTL 电路。
    这是整个流程中最耗时的步骤（通常 5-15 分钟）。

    综合报告包含:
    - latency（延迟）：时钟周期总数
    - interval（启动间隔）：流水线两次调用之间的最小间隔
    - clock_period_ns（时钟周期）：估算的时钟周期
    - resources（资源消耗）：LUT, FF, DSP, BRAM_18K, URAM
    """

    def __init__(self, executor: SecureToolExecutor | None = None,
                 *, workspace_root: str | Path = "/workspace") -> None:
        self._executor = executor or SecureToolExecutor(workspace_root=workspace_root)

    def run(self, build_dir: Path, files: dict[str, str], synth_sources: list[str],
            top: str, part: str = config.DEFAULT_PART,
            clock_ns: float = config.DEFAULT_CLOCK_NS):
        """运行 C 综合。"""
        prepared = _prepare_cpp17_sources(files)
        return self._executor.synth(
            build_dir, prepared, synth_sources=synth_sources,
            top=top, part=part, clock_ns=clock_ns,
        )


class CoSimTool:
    """
    C/RTL 联合仿真工具适配器。

    CoSim 验证综合生成的 RTL 电路与原始 C++ 代码行为一致。
    CSim 的 FIFO 是无界的（隐藏了死锁），而 CoSim 的 FIFO 默认深度为 2，
    因此 streaming/dataflow 的 bug 只在 CoSim 阶段暴露。

    CoSim 是最昂贵的工具调用（~15-20 credits）。
    """

    def __init__(self, executor: SecureToolExecutor | None = None,
                 *, workspace_root: str | Path = "/workspace") -> None:
        self._executor = executor or SecureToolExecutor(workspace_root=workspace_root)

    def run(self, build_dir: Path, files: dict[str, str], synth_sources: list[str],
            tb_sources: list[str], top: str,
            part: str = config.DEFAULT_PART, clock_ns: float = config.DEFAULT_CLOCK_NS):
        """运行 C/RTL 联合仿真。"""
        prepared = _prepare_cpp17_sources(files)
        return self._executor.cosim(
            build_dir, prepared, synth_sources=synth_sources,
            tb_sources=tb_sources, top=top, part=part, clock_ns=clock_ns,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ToolServer — 统一的工具服务器
# ═══════════════════════════════════════════════════════════════════════════════

class ToolServer(HarnessToolServer):
    """
    可替换的 ToolServer，其工具委托给 SecureToolExecutor。

    工具通过 .executor 属性暴露，调用方可以在测试中替换为 fake executor
    而不需要修改工具类。

    ToolServer 提供三个方法:
    - server.csim(kernel_code)   → ToolResult
    - server.synth(kernel_code)  → ToolResult
    - server.cosim(kernel_code)  → ToolResult

    每个调用都会消耗 Budget 中的 credits，并记录到 transcript（调用日志）。
    """

    def __init__(self, task, budget, run_root: Path,
                 workspace_root: str | Path | None = None,
                 executor: SecureToolExecutor | None = None) -> None:
        """
        参数:
            task:           HLS 任务对象
            budget:         预算管理器
            run_root:       运行根目录
            workspace_root: 工作空间根目录（工具在此执行）
            executor:       SecureToolExecutor（可选，用于测试注入）
        """
        super().__init__(task, budget, run_root)

        # 允许外部注入 executor（用于测试）
        if executor is not None:
            self.executor = executor
        else:
            ws = workspace_root if workspace_root else str(Path(run_root).resolve())
            self.executor = SecureToolExecutor(
                workspace_root=ws,
                source_transformer=_prepare_cpp17_sources,
            )

        # 构建三个工具适配器，共享同一个 executor
        self._csim = CSimTool(self.executor, getattr(task, "public_data_files", None))
        self._synth = SynthTool(self.executor)
        self._cosim = CoSimTool(self.executor)
