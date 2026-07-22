# =============================================================================
# FPT26 Track-A Agent v3 — LLM 后端工厂 (LLM Backend Factory)
# =============================================================================
# 【功能概述】
#   本文件是 LLM（大语言模型）后端的工厂函数。它封装了创建 LLM 客户端的逻辑，
#   根据环境变量和命令行参数自动选择合适的后端。
#
# 【这是你应该看的第 16 个文件】
#
# 【后端选项】
#   auto:       自动检测（优先检查 FPT26_LLM_API_KEY 环境变量）
#   openrouter: 使用 OpenRouter API（api.openrouter.ai）
#   custom:     自定义 OpenAI 兼容 API（通过 FPT26_LLM_BASE_URL 配置）
#   scripted:   离线模式（回放预定义的响应，不调用真实 API，用于测试）
#
# 【环境变量配置】
#   FPT26_LLM_API_KEY        API 密钥
#   FPT26_LLM_MODEL          模型名称（如 "claude-sonnet-5"）
#   FPT26_LLM_TEMPERATURE    温度参数（默认 0.7）
#   FPT26_LLM_MAX_TOKENS     最大输出 token 数（默认 4096）
#   FPT26_LLM_TIMEOUT_SECONDS 超时时间（默认 180 秒）
#   FPT26_LLM_MAX_RETRIES    最大重试次数（默认 2）
# =============================================================================

from __future__ import annotations

import os

from llm4hls.llm import (
    LLMClient,
    OpenAICompatClient,
    OpenRouterClient,
    ScriptedClient,
    create_llm as _official_create_llm,  # 官方 llm4hls 的 LLM 创建函数
)
from agent.integrations.llm.protocol import LLMExecutor, LLMConfig


def create_llm(backend: str = "auto") -> LLMExecutor:
    """
    根据环境变量或显式选择创建 LLM 执行器。

    返回的 LLMExecutor 封装了底层的 LLM 客户端，
    提供重试、超时和 token 预算追踪能力。

    参数:
        backend: "auto" | "openrouter" | "custom" | "scripted"

    返回:
        LLMExecutor: 封装了重试/超时/预算追踪的 LLM 客户端

    用法:
        llm = create_llm("auto")
        response = llm.complete(system_prompt, user_prompt)
    """
    # 创建底层的 LLM 客户端（来自 llm4hls 官方实现）
    raw = _official_create_llm(backend)

    # 构建配置对象（优先使用环境变量，再使用默认值）
    cfg = LLMConfig(
        model=getattr(raw, "model", "") or os.environ.get("FPT26_LLM_MODEL", ""),
        temperature=float(os.environ.get("FPT26_LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.environ.get("FPT26_LLM_MAX_TOKENS", "4096")),
        timeout_s=float(os.environ.get("FPT26_LLM_TIMEOUT_SECONDS", "180")),
        max_retries=int(os.environ.get("FPT26_LLM_MAX_RETRIES", "2")),
    )

    # 用 LLMExecutor 包装，提供重试/超时/预算追踪
    return LLMExecutor(raw, cfg)


def create_scripted_client(responses: list[str]) -> LLMExecutor:
    """
    创建离线脚本化 LLM 客户端（不回放预定义响应）。

    用于测试场景，不调用任何外部 API。

    参数:
        responses: 预定义的响应列表（按顺序回放）

    返回:
        LLMExecutor: 脚本化的 LLM 客户端
    """
    from agent.integrations.llm.scripted import ScriptedLLM
    return LLMExecutor(ScriptedLLM(responses), LLMConfig(model="scripted"))
