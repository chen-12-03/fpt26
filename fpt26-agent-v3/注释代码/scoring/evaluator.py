# =============================================================================
# FPT26 Track-A Agent v3 — 评分编排 (Scoring Orchestration)
# =============================================================================
# 【功能概述】
#   本文件是评分流程的编排核心。它协调了从 hidden CSim 到最终评分的全部步骤。
#   评分的关键在于：用**隐藏的测试平台**重新验证内核，用**独立的评估**确定锚点，
#   最后通过评分公式产生最终分数。
#
# 【这是你应该看的第 14 个文件】
#
# 【评分流程（9 个步骤）】
#
#   1. Hidden CSim          用隐藏测试平台验证候选代码的功能正确性
#   2. Candidate Synthesis  综合候选代码，获取 PPA 数据
#   3. Candidate CoSim      联合仿真（仅结构型任务）
#   4. Starter Anchor Eval  独立评估 starter 代码的所有门控
#   5. Reference Anchor Eval  独立评估 reference 代码的所有门控（如果存在）
#   6. Anchor Selection     选择 starter 或 reference 作为锚点
#   7. Cost/Time Accounting  汇总 Submission + Evaluator 的成本和时间
#   8. Grade                调用 grade_with_profile 产生 Scorecard
#   9. Reference Scorecard  使用 reference 锚点产生参考评分卡
#
#   【关键设计：独立锚点评估】
#   Starter 和 Reference 各自接受独立的门控评估（_evaluate_anchor_source）。
#   候选代码的门控结果不会泄露到锚点资格认证中。
# =============================================================================

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from agent.runner import CSimTool, SynthTool, CoSimTool
from agent.candidate.validator import record_synth_gates, record_cosim_gate
from agent.models import (
    AnchorEvidence,
    CandidateEvaluation,
    CoSimGateEvidence,
    EvaluationAccounting,
    FrequencyGateEvidence,
    InterfaceGateEvidence,
    ResourceGateEvidence,
)
from agent.validation import frequency_gate as _freq_gate_fn
from agent.validation import resource_gate as _res_gate_fn
from scoring.scoring_v3 import (
    Anchor,
    QoREvidence,
    TaskScoringConfig,
    ValidityGates,
    verified_available_resources,
)
from scoring.profiles import grade_with_profile


# ═══════════════════════════════════════════════════════════════════════════════
# 独立锚点源评估
# ═══════════════════════════════════════════════════════════════════════════════

def _evaluate_anchor_source(
    *, source_code: str, source_label: str,  # "starter" | "reference"
    task: Any, grade_root: Path, requires_cosim: bool,
) -> CandidateEvaluation:
    """
    对锚点源代码独立运行所有必需的门控。

    这个函数拥有自己的 CSim、Synth、频率、资源和（需要时）CoSim 运行。
    它从不读取候选代码的门控状态，保证了锚点评估的独立性。

    独立评估意味着：
    - starter 可能无法通过某些门控（这在某些任务中是正常的）
    - reference 如果存在且通过所有门控，会被优先选为锚点
    """
    source_sha = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
    ev = CandidateEvaluation(source_sha256=source_sha, stage=source_label)

    # 接口门控
    from agent.candidate.validator import InterfaceValidator
    try:
        iface_validator = InterfaceValidator.from_source(task.top, source_code)
    except ValueError:
        ev.interface = InterfaceGateEvidence(ok=False, reason="contract_build_failed")
        ev.fail("contract_build_failed")
        return ev
    result = iface_validator.validate(source_code)
    ev.interface = InterfaceGateEvidence(
        ok=result.ok, reason=result.reason,
        fingerprint=result.fingerprint,
        canonical_signature=result.canonical_signature,
        required_includes_present=result.required_includes_present,
    )
    if not result.ok:
        ev.fail(result.reason or "interface")
        return ev

    # CSim 门控（使用隐藏测试平台）
    source_files = task.assemble(source_code, task.hidden_tb_code, task.hidden_tb_name)
    data_files = getattr(task, "hidden_data_files", None) or None
    csim_result = CSimTool().run(
        grade_root / f"grade_csim_{source_label}", source_files,
        top=task.top, part=task.part, clock_ns=task.clock_ns,
        data_files=data_files,
    )
    csim_ok = bool(getattr(csim_result, "ok", False))
    ev.csim = "pass" if csim_ok else "fail"
    if not csim_ok:
        ev.fail("csim")
        return ev

    # Synth 门控
    synth_files = dict(getattr(task, "headers", {}))
    synth_files[task.kernel_name] = source_code
    synth_result = SynthTool().run(
        grade_root / f"grade_synth_{source_label}", synth_files,
        synth_sources=[task.kernel_name],
        top=task.top, part=task.part, clock_ns=task.clock_ns,
    )
    synth_ok = bool(getattr(synth_result, "ok", False))
    report = getattr(synth_result, "report", None) if synth_ok else None
    ev.synth = "pass" if (synth_ok and report is not None) else "fail"
    if report is None:
        ev.fail("synth")
        return ev

    # 频率门控
    freq = _freq_gate_fn(report, task.clock_ns)
    ev.frequency = FrequencyGateEvidence(
        ok=freq.ok, reason=freq.reason,
        target_clock_ns=freq.target_clock_ns,
        candidate_clock_ns=freq.candidate_clock_ns,
        frequency_mhz=freq.frequency_mhz,
    )
    if not freq.ok:
        ev.fail(freq.reason or "frequency")
        return ev

    # 资源门控
    res = _res_gate_fn(report)
    ev.resource = ResourceGateEvidence(
        ok=res.ok, reason=res.reason,
        resources=dict(res.resources), available=dict(res.available),
    )
    if not res.ok and res.reason != "resource_capacity_missing":
        ev.fail(res.reason or "resource")
        return ev

    # PPA 数据
    ev.synth_latency = (
        report.latency_worst
        if getattr(report, "latency_worst", None) is not None
        else getattr(report, "latency_avg", None)
    )
    ev.synth_ii = getattr(report, "interval_max", None)
    ev.synth_clock_ns = getattr(report, "clock_period_ns", None)
    ev.synth_resources = dict(getattr(report, "resources", {}) or {})

    # CoSim 门控（仅结构型任务需要）
    if requires_cosim:
        cosim_result = CoSimTool().run(
            grade_root / f"grade_cosim_{source_label}", source_files,
            synth_sources=[task.kernel_name],
            tb_sources=[task.hidden_tb_name],
            top=task.top, part=task.part, clock_ns=task.clock_ns,
        )
        payload = getattr(cosim_result, "cosim", None)
        cosim_ok = bool(
            getattr(cosim_result, "ok", False)
            and payload is not None
            and getattr(payload, "passed", False)
        )
        ev.cosim = CoSimGateEvidence(
            ok=cosim_ok, source_sha256=source_sha,
            latency_max=getattr(payload, "latency_max", None) if payload else None,
        )
        if not cosim_ok:
            ev.fail("cosim")
            return ev

    ev.accepted = True
    return ev


# ═══════════════════════════════════════════════════════════════════════════════
# 主评分步骤: evaluate_and_score
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_and_score(state: Any, *, accounting: EvaluationAccounting | None = None) -> Any:
    """
    运行评分流程: hidden-csim → synth(cand) → synth(starter) → synth(ref) → 可选cosim → 评分。

    原地修改 state（scorecard, ref_scorecard, gates），并返回它。

    参数:
        state:      包含 task、kernel、config 的 RunState
        accounting: 正式评估时必需。如果缺省，回退到 state.server.budget.spent

    返回:
        更新后的 RunState（含 scorecard 和 ref_scorecard）
    """
    if not state.config.score:
        return state  # Submission 角色不需要评分

    task = state.task
    kernel = state.kernel
    grade_root = Path(state.config.output_root) / task.id / "grade"
    _start = time.monotonic()

    # ---- 1. Hidden CSim（候选代码有效性门控）----
    # 使用隐藏测试平台（不是公共测试平台）验证候选代码
    hidden_files = task.assemble(kernel, task.hidden_tb_code, task.hidden_tb_name)
    data_files = getattr(task, "hidden_data_files", None) or None
    csim = CSimTool().run(
        grade_root / "grade_csim", hidden_files,
        top=task.top, part=task.part, clock_ns=task.clock_ns,
        data_files=data_files,
    )
    state.csim_ok = csim.ok
    if not csim.ok:
        state.status = "failed"
        state.stop_reason = "hidden_csim_failed"
        state.scorecard = None
        return state

    # ---- 2. 候选代码综合 ----
    cand_files = dict(task.headers)
    cand_files[task.kernel_name] = kernel
    cand_synth = SynthTool().run(
        grade_root / "grade_synth_cand", cand_files,
        synth_sources=[task.kernel_name],
        top=task.top, part=task.part, clock_ns=task.clock_ns,
    )
    state.synth_ok = cand_synth.ok
    if not cand_synth.ok or cand_synth.report is None:
        state.status = "failed"
        state.stop_reason = "candidate_synth_failed"
        state.scorecard = None
        return state
    if not record_synth_gates(state, cand_synth, stage="evaluator_candidate_synth"):
        reason = (
            (state.metadata.get("frequency_gate") or {}).get("reason")
            if not state.frequency_ok
            else (state.metadata.get("resource_gate") or {}).get("reason")
        )
        state.status = "failed"
        state.stop_reason = str(reason or "candidate_target_gate_failed")
        state.scorecard = None
        return state

    # ---- 3. 候选代码 CoSim（如需要）----
    cosim = None
    cosim_ok: bool | None = None
    cosim_latency: int | None = None
    if task.requires_cosim:
        cosim = CoSimTool().run(
            grade_root / "grade_cosim", hidden_files,
            synth_sources=[task.kernel_name],
            tb_sources=[task.hidden_tb_name],
            top=task.top, part=task.part, clock_ns=task.clock_ns,
        )
        cosim_ok = record_cosim_gate(state, cosim, stage="evaluator_hidden_cosim", source_code=kernel)
        cosim_report = getattr(cosim, "cosim", None)
        if not cosim_ok:
            state.status = "failed"
            state.stop_reason = "required_cosim_failed"
            state.scorecard = None
            return state
        cosim_latency = cosim_report.latency_max
    else:
        state.cosim_ok = True

    # ---- 4. 独立锚点评估 ----
    # 每个锚点源运行自己的 CSim、Synth、频率、资源和 CoSim。
    # 候选代码的门控状态不会泄露到锚点评估中。
    starter_eval = _evaluate_anchor_source(
        source_code=task.kernel_code, source_label="starter",
        task=task, grade_root=grade_root, requires_cosim=task.requires_cosim,
    )

    ref_eval = None
    if task.reference_code:
        ref_eval = _evaluate_anchor_source(
            source_code=task.reference_code, source_label="reference",
            task=task, grade_root=grade_root, requires_cosim=task.requires_cosim,
        )

    # ---- 5. 锚点选择 ----
    from agent.candidate.selector import select_anchor
    anchor_evidence = select_anchor(starter_eval, ref_eval, requires_cosim=task.requires_cosim)

    # ---- 6. 构建评分数据结构 ----
    cfg = TaskScoringConfig(
        task_id=task.id, task_type=task.type, difficulty=task.difficulty,
        requires_cosim=task.requires_cosim, budget_limit=task.budget,
        task_clock_ns=task.clock_ns,
    )

    anchor = Anchor(
        source=anchor_evidence.source, valid=anchor_evidence.valid,
        latency=anchor_evidence.latency, ii=anchor_evidence.ii,
        clock_ns=anchor_evidence.clock_ns,
        resources=dict(anchor_evidence.resources),
        available=dict(anchor_evidence.available),
    )

    cand_lat = (
        cand_synth.report.latency_worst or cand_synth.report.latency_avg
        if cand_synth.ok and cand_synth.report else None
    )
    evidence = QoREvidence(
        candidate_latency=cand_lat,
        candidate_ii=cand_synth.report.interval_max if cand_synth.ok and cand_synth.report else None,
        candidate_clock_ns=(
            cand_synth.report.clock_period_ns
            if cand_synth.ok and cand_synth.report else task.clock_ns
        ),
        cosim_latency=cosim_latency,
        candidate_resources=cand_synth.report.resources if cand_synth.ok and cand_synth.report else {},
    )
    gates = ValidityGates(
        hidden_csim_pass=csim.ok, hidden_cosim_pass=cosim_ok,
        synth_pass=cand_synth.ok, resource_capacity_pass=state.resource_ok,
    )

    # ---- 7. 确定成本/时间 ----
    if accounting is not None:
        cost_spent = accounting.total_credits
        wall_time_s = accounting.total_wall_seconds
    else:
        budget_obj = state.server.budget
        cost_spent = budget_obj.spent if hasattr(budget_obj, 'spent') else 0
        wall_time_s = time.monotonic() - _start

    # ---- 8. 评分 ----
    scorecard = grade_with_profile(
        task_cfg=cfg, anchor=anchor, evidence=evidence,
        scoring_profile=getattr(state.config, "scoring_profile", "balanced"),
        cost_spent=cost_spent, wall_time_s=wall_time_s, gates=gates,
        accounting=accounting,
    )
    state.scorecard = scorecard
    state.metadata["anchor_evidence"] = anchor_evidence.to_dict()

    # Fail-closed: 无效锚点 → 分数归零
    if not anchor_evidence.passes_all_required_gates:
        scorecard.valid = False
        if scorecard.gate_reason in ("passed", "", None):
            scorecard.gate_reason = (
                anchor_evidence.failure_reason
                or f"anchor_invalid: {anchor_evidence.source}"
            )
        scorecard.score = 0.0
        state.status = "failed"
        if not state.stop_reason:
            state.stop_reason = scorecard.gate_reason

    # ---- 9. Reference 锚点评分卡 ----
    if ref_eval is not None and ref_eval.accepted:
        ref_anchor = Anchor(
            source="reference", valid=True,
            latency=ref_eval.synth_latency, ii=ref_eval.synth_ii,
            clock_ns=ref_eval.synth_clock_ns,
            resources=dict(ref_eval.synth_resources),
            available=dict(ref_eval.resource.available) if ref_eval.resource else {},
        )
        ref_scorecard = grade_with_profile(
            task_cfg=cfg, anchor=ref_anchor, evidence=evidence,
            scoring_profile=getattr(state.config, "scoring_profile", "balanced"),
            cost_spent=cost_spent, wall_time_s=wall_time_s, gates=gates,
            accounting=accounting,
        )
        state.ref_scorecard = ref_scorecard

    return state
