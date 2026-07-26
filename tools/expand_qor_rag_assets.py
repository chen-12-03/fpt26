#!/usr/bin/env python3
"""Expand QoR-RAG seed rules and curate measured public submission cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.knowledge import KNOWLEDGE_SCHEMA_VERSION, KnowledgeEntry
from agent.qor_rag_curate import curate_submission_report


EXTRA_SEED_RULES: list[dict[str, Any]] = [
    {
        "id": "hlsgen.pipeline.outer_loop_caution",
        "family": "pipeline",
        "preconditions": ["An outer loop controls throughput.", "Inner loops or memory accesses may become concurrent."],
        "action": "Pipeline the outer loop only when the report and source prove inner-loop concurrency is intended and memory ports can support it.",
        "expected_signal": "Function interval improves without new memory-port II warnings or large resource growth.",
        "contraindications": ["Do not pipeline an outer loop as a default latency fix.", "Avoid this when inner loops have variable bounds or shared mutable state."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#pipeline-and-ii",
        "tags": ["pipeline", "outer_loop", "memory_port", "concurrency"],
    },
    {
        "id": "hlsgen.pipeline.rewind_only_streaming",
        "family": "pipeline",
        "preconditions": ["A loop pipeline handles back-to-back transactions.", "State carried between loop invocations is understood."],
        "action": "Use PIPELINE rewind only for a valid continuous loop pipeline whose state behavior remains correct across transactions.",
        "expected_signal": "Back-to-back interval improves while CSim and required CoSim preserve transaction behavior.",
        "contraindications": ["Do not use rewind to mask a deadlock.", "Do not use rewind on a loop with invalid persistent state semantics."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#pipeline-and-ii",
        "tags": ["pipeline", "rewind", "transaction", "state"],
    },
    {
        "id": "hlsgen.unroll.resource_stop",
        "family": "unroll",
        "preconditions": ["A prior unroll factor was measured.", "The next factor would increase replicated operators or banks."],
        "action": "Stop increasing the unroll factor once worst-resource growth exceeds effective latency improvement.",
        "expected_signal": "Candidate selection avoids Q_HW regressions from area-dominated unrolls.",
        "contraindications": ["Do not compare cycle latency alone.", "Do not extrapolate from one target part to another."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#report-driven-checks",
        "tags": ["unroll", "resource", "q_hw", "factor", "area"],
    },
    {
        "id": "hlsgen.unroll.variable_bound_guard",
        "family": "unroll",
        "preconditions": ["A loop has a dynamic or unproven trip count.", "The candidate proposes loop unrolling."],
        "action": "Avoid unrolling dynamic-bound loops unless a fixed upper bound and validation budget are explicit.",
        "expected_signal": "Synthesis avoids capacity blowups and unsupported full-unroll behavior.",
        "contraindications": ["Do not full-unroll a data-dependent loop.", "Do not invent trip counts absent from source or report evidence."],
        "source": "third_party/hls-generator/references/hls-modeling-strategy.md#loop-bounds-and-trip-counts",
        "tags": ["unroll", "variable_bound", "trip_count", "capacity"],
    },
    {
        "id": "hlsgen.array_partition.complete_small_local",
        "family": "array_partition",
        "preconditions": ["A small local array is indexed with parallel lane accesses.", "Complete banking is within LUT/FF budget."],
        "action": "Use complete ARRAY_PARTITION on the small local dimension that maps to concurrent lane reads.",
        "expected_signal": "The lane loop reaches lower II with bounded register growth.",
        "contraindications": ["Do not complete-partition large external arrays.", "Do not partition a dimension not used by the concurrent accesses."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#array-partition-and-reshape",
        "tags": ["array_partition", "complete", "local_array", "lane", "bank"],
    },
    {
        "id": "hlsgen.array_partition.cyclic_stride",
        "family": "array_partition",
        "preconditions": ["Accesses are strided across a known dimension.", "The modulo pattern maps lanes across banks."],
        "action": "Prefer cyclic ARRAY_PARTITION when strided lane accesses need distinct banks.",
        "expected_signal": "Bank conflicts fall and achieved II improves on the measured loop.",
        "contraindications": ["Do not use cyclic banking for contiguous packed-word bandwidth.", "Do not choose a factor unrelated to the lane/stride pattern."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#array-partition-and-reshape",
        "tags": ["array_partition", "cyclic", "stride", "bank_conflict"],
    },
    {
        "id": "hlsgen.array_reshape.no_partition_mix",
        "family": "array_reshape",
        "preconditions": ["A candidate proposes both reshape and partition on the same variable.", "The access pattern is not independently proven for both."],
        "action": "Choose either ARRAY_RESHAPE for packed adjacent bandwidth or ARRAY_PARTITION for independent banks, not both on the same variable.",
        "expected_signal": "The directive set remains explainable and avoids redundant storage expansion.",
        "contraindications": ["Do not stack storage directives to guess around an II issue.", "Do not reshape irregular access patterns."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#array-partition-and-reshape",
        "tags": ["array_reshape", "array_partition", "mutual_exclusion", "storage"],
    },
    {
        "id": "hlsgen.dataflow.shared_state_guard",
        "family": "dataflow",
        "preconditions": ["A DATAFLOW region has shared arrays or globals between stages.", "Stage ownership is ambiguous."],
        "action": "Do not add DATAFLOW until producer/consumer ownership is separated by streams or clearly single-writer buffers.",
        "expected_signal": "Avoids synthesis or CoSim failures from ambiguous shared mutation.",
        "contraindications": ["Do not rely on CSim to prove task-level scheduling safety.", "Do not split functions that share hidden global state."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#dataflow",
        "tags": ["dataflow", "shared_state", "producer", "consumer", "cosim"],
    },
    {
        "id": "hlsgen.stream_fifo.depth_from_burst",
        "family": "stream_fifo",
        "preconditions": ["Producer and consumer burst sizes differ.", "The FIFO is explicit in source or report evidence."],
        "action": "Set stream depth from the measured burst/rate mismatch instead of using an arbitrary large FIFO.",
        "expected_signal": "Required CoSim passes and FIFO resource use remains bounded.",
        "contraindications": ["Do not hide ordering bugs with large depths.", "Do not tune FIFO depth without a DATAFLOW or stream boundary."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#dataflow",
        "tags": ["stream_fifo", "depth", "burst", "dataflow", "cosim"],
    },
    {
        "id": "hlsgen.stream_fifo.axis_tlast_contract",
        "family": "stream_fifo",
        "preconditions": ["The interface uses AXIS side channels or TLAST.", "The testbench expects frame boundaries."],
        "action": "Preserve side-channel fields and TLAST policy when optimizing stream loops.",
        "expected_signal": "CSim and required CoSim preserve packet framing while throughput improves.",
        "contraindications": ["Do not drop side-channel fields during type simplification.", "Do not change TLAST generation without a matching interface contract."],
        "source": "third_party/hls-generator/references/hls-stream-codec-template-family.md#stream-codec-framing",
        "tags": ["stream_fifo", "axis", "tlast", "side_channel", "framing"],
    },
    {
        "id": "hlsgen.memory_banking.distinct_m_axi_bundles",
        "family": "memory_banking",
        "preconditions": ["Independent external memories are read or written concurrently.", "The top-level interface uses m_axi ports."],
        "action": "Assign independent m_axi ports to distinct bundle names when concurrent bandwidth is required.",
        "expected_signal": "Interface arbitration pressure falls and memory throughput improves.",
        "contraindications": ["Do not split bundles for intentionally shared arbitration.", "Keep depth concrete for C/RTL co-simulation."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#multi-m-axi-bundles",
        "tags": ["memory_banking", "m_axi", "bundle", "bandwidth", "interface"],
    },
    {
        "id": "hlsgen.memory_banking.local_buffer_before_ports",
        "family": "memory_banking",
        "preconditions": ["The kernel repeatedly accesses external memory.", "A local reuse window or tile is visible."],
        "action": "Prefer explicit local buffering for reuse before increasing external memory ports.",
        "expected_signal": "External memory transactions per operation fall and local storage growth is bounded.",
        "contraindications": ["Do not introduce a buffer without a reuse story.", "Do not change output ordering or boundary behavior."],
        "source": "third_party/hls-generator/references/hls-project-structure-patterns.md#hotspot-file-organization",
        "tags": ["memory_banking", "local_buffer", "reuse", "m_axi"],
    },
    {
        "id": "hlsgen.loop_flatten.perfect_nest_only",
        "family": "loop_flatten",
        "preconditions": ["A nested loop is perfect or semi-perfect.", "Flattening does not change loop-carried state semantics."],
        "action": "Apply LOOP_FLATTEN only to a compatible nest with proven bounds and no intervening side effects.",
        "expected_signal": "Loop overhead or scheduling interval improves without functional changes.",
        "contraindications": ["Do not flatten imperfect nests with boundary code.", "Do not flatten when dependence analysis is uncertain."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#pipeline-and-ii",
        "tags": ["loop_flatten", "perfect_nest", "bounds", "dependence"],
    },
    {
        "id": "hlsgen.loop_fission.isolate_memory_stage",
        "family": "loop_fission",
        "preconditions": ["One loop mixes memory movement and compute.", "Separate stages can communicate through a bounded buffer or stream."],
        "action": "Split the loop only when stage boundaries and storage ownership are explicit.",
        "expected_signal": "The bottleneck stage becomes independently pipelinable or dataflow-capable.",
        "contraindications": ["Do not split loops with ambiguous dependencies.", "Do not duplicate memory traffic while chasing parallelism."],
        "source": "third_party/hls-generator/references/hls-task-parallel-strategy.md#task-regions-and-dataflow-boundaries",
        "tags": ["loop_fission", "split", "stage", "memory", "dataflow"],
    },
    {
        "id": "hlsgen.loop_fusion.reduce_passes",
        "family": "loop_fusion",
        "preconditions": ["Adjacent loops traverse the same bounded range.", "Fusion does not increase recurrence or memory-port conflicts."],
        "action": "Fuse adjacent passes only when it reduces memory traffic without worsening II.",
        "expected_signal": "Latency or memory transactions fall while achieved II remains stable.",
        "contraindications": ["Do not fuse loops with conflicting pipeline schedules.", "Do not fuse when it creates additional live-range pressure."],
        "source": "third_party/hls-generator/references/hls-task-parallel-strategy.md#task-regions-and-dataflow-boundaries",
        "tags": ["loop_fusion", "fuse", "passes", "memory_traffic"],
    },
    {
        "id": "hlsgen.reduction.float_associativity_guard",
        "family": "reduction",
        "preconditions": ["The reduction uses floating-point arithmetic.", "A candidate changes operation order."],
        "action": "Preserve floating-point associativity semantics unless the task contract allows numerical differences.",
        "expected_signal": "CSim remains stable under the public tolerance and timing does not regress.",
        "contraindications": ["Do not build a tree for bit-exact floating-point code without permission.", "Do not enable unsafe math silently."],
        "source": "third_party/hls-generator/references/hls-stencil-reduction-gemm-patterns.md#reduction-trees",
        "tags": ["reduction", "floating_point", "associativity", "unsafe_math"],
    },
    {
        "id": "hlsgen.reduction.multi_accumulator_integer",
        "family": "reduction",
        "preconditions": ["An integer associative reduction has a fixed trip count.", "Resource headroom supports multiple accumulators."],
        "action": "Use a small number of independent accumulators before a final combine, then measure Q_HW.",
        "expected_signal": "Recurrence pressure falls and effective latency improves within area limits.",
        "contraindications": ["Do not change overflow semantics.", "Do not over-unroll beyond measured resource headroom."],
        "source": "third_party/hls-generator/references/hls-stencil-reduction-gemm-patterns.md#reduction-trees",
        "tags": ["reduction", "integer", "multi_accumulator", "recurrence", "unroll"],
    },
    {
        "id": "hlsgen.gemm.partition_k_dimension_guard",
        "family": "gemm",
        "preconditions": ["A GEMM-style kernel reuses local tiles.", "The proposed partition targets the accumulation or lane dimension."],
        "action": "Bank only the local tile dimension that is read concurrently by the unrolled compute lanes.",
        "expected_signal": "Compute-lane II improves without partitioning unrelated matrices.",
        "contraindications": ["Do not complete-partition full matrices.", "Do not change tile shape without measuring memory and DSP pressure."],
        "source": "third_party/hls-generator/references/hls-stencil-reduction-gemm-patterns.md#tiled-gemm",
        "tags": ["gemm", "tile", "array_partition", "lane", "dsp"],
    },
    {
        "id": "hlsgen.gemm.dsp_clock_guard",
        "family": "gemm",
        "preconditions": ["A GEMM candidate increases DSP parallelism.", "Estimated clock or DSP use worsens."],
        "action": "Compare clock-adjusted latency and worst-resource growth before accepting additional MAC lanes.",
        "expected_signal": "Q_HW improves rather than cycle latency alone.",
        "contraindications": ["Do not accept a lower cycle count with severe clock degradation.", "Do not exceed DSP headroom."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#report-driven-checks",
        "tags": ["gemm", "dsp", "clock", "q_hw", "resource"],
    },
    {
        "id": "hlsgen.stencil.border_policy_guard",
        "family": "stencil",
        "preconditions": ["A stencil kernel handles image/grid borders.", "The candidate changes buffering or loop order."],
        "action": "Preserve the existing border policy exactly when introducing window or line-buffer optimizations.",
        "expected_signal": "Public CSim remains bit-equivalent while memory reuse improves.",
        "contraindications": ["Do not skip border elements for throughput.", "Do not change padding, clamp, or zero-fill behavior silently."],
        "source": "third_party/hls-generator/references/hls-stencil-reduction-gemm-patterns.md#stencil-and-window-patterns",
        "tags": ["stencil", "border", "line_buffer", "window", "correctness"],
    },
    {
        "id": "hlsgen.stencil.shift_register_small_window",
        "family": "stencil",
        "preconditions": ["The stencil has a small fixed 1D window.", "Neighbor reuse is local and bounded."],
        "action": "Use a shift-register style local window before larger line-buffer restructuring.",
        "expected_signal": "Repeated loads fall and loop II improves with small FF/LUT growth.",
        "contraindications": ["Do not use for large 2D images without a line-buffer plan.", "Do not alter warm-up or boundary behavior."],
        "source": "third_party/hls-generator/references/hls-stencil-reduction-gemm-patterns.md#stencil-and-window-patterns",
        "tags": ["stencil", "shift_register", "window", "reuse"],
    },
    {
        "id": "hlsgen.bitwidth.range_first",
        "family": "bitwidth",
        "preconditions": ["The source uses ap_int or ap_fixed.", "Value range or error budget is known."],
        "action": "Narrow bitwidth only when range and quantization behavior are explicit in source or task contract.",
        "expected_signal": "DSP/LUT/FF use falls without public CSim mismatch.",
        "contraindications": ["Do not infer a narrower type from one test vector.", "Do not change saturation or rounding semantics silently."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#fixed-point-and-floating-point",
        "tags": ["bitwidth", "ap_int", "ap_fixed", "range", "quantization"],
    },
    {
        "id": "hlsgen.bitwidth.interface_width_guard",
        "family": "bitwidth",
        "preconditions": ["A type-width change touches top-level ports.", "The testbench or host interface expects a fixed ABI."],
        "action": "Keep top-level interface widths stable; narrow only internal temporaries unless the contract allows an ABI change.",
        "expected_signal": "Interface validation remains pass while internal resource use can improve.",
        "contraindications": ["Do not change top argument types in optimize mode.", "Do not break m_axi word alignment."],
        "source": "third_party/hls-generator/references/hls-project-structure-patterns.md#bundle-and-depth-stability",
        "tags": ["bitwidth", "interface", "abi", "m_axi", "top_function"],
    },
    {
        "id": "hlsgen.math_kernel.unsafe_math_opt_in",
        "family": "math_kernel",
        "preconditions": ["The kernel uses floating-point math or transcendental operations.", "The task contract allows approximate numerical behavior."],
        "action": "Enable unsafe math or algebraic reassociation only when explicitly allowed and validated against tolerance.",
        "expected_signal": "Latency or DSP use improves while CSim remains within tolerance.",
        "contraindications": ["Do not assume unsafe math for sensitive kernels.", "Do not change NaN, rounding, or exception-sensitive behavior silently."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#fixed-point-and-floating-point",
        "tags": ["math_kernel", "float", "unsafe_math", "tolerance"],
    },
    {
        "id": "hlsgen.math_kernel.cordic_intent_only",
        "family": "math_kernel",
        "preconditions": ["The confirmed design intent is trigonometric or vector rotation.", "CORDIC numeric format and iteration count are explicit."],
        "action": "Use CORDIC-specific structure only for confirmed CORDIC intent; otherwise preserve existing math code.",
        "expected_signal": "DSP/latency tradeoff improves for the intended transform family.",
        "contraindications": ["Do not introduce CORDIC for unrelated bit rotations.", "Do not change numeric scale without a contract."],
        "source": "third_party/hls-generator/references/hls-fft-cordic-template-family.md#cordic",
        "tags": ["math_kernel", "cordic", "fixed_point", "rotation"],
    },
    {
        "id": "hlsgen.math_kernel.fir_symmetry",
        "family": "math_kernel",
        "preconditions": ["The kernel is a FIR filter.", "Coefficients are symmetric or decimation/interpolation intent is explicit."],
        "action": "Exploit FIR symmetry or specialized structure only when coefficients and sample ordering prove it.",
        "expected_signal": "Multiplier count or latency improves with identical public output.",
        "contraindications": ["Do not assume coefficient symmetry.", "Do not change sample phase or decimator schedule."],
        "source": "third_party/hls-generator/references/hls-fir-template-family.md#fir-patterns",
        "tags": ["math_kernel", "fir", "dsp", "coefficient", "symmetry"],
    },
    {
        "id": "hlsgen.interface.depth_concrete",
        "family": "interface",
        "preconditions": ["A top-level pointer or m_axi interface is present.", "C/RTL co-simulation or host modeling needs bounded memory."],
        "action": "Keep m_axi depth concrete and consistent with public testbench allocation.",
        "expected_signal": "Interface checks and CoSim memory modeling remain valid.",
        "contraindications": ["Do not delete depth metadata to simplify pragmas.", "Do not use a depth smaller than the public test extent."],
        "source": "third_party/hls-generator/references/hls-project-structure-patterns.md#bundle-and-depth-stability",
        "tags": ["interface", "depth", "m_axi", "cosim"],
    },
    {
        "id": "hlsgen.interface.s_axilite_return",
        "family": "interface",
        "preconditions": ["The kernel uses accelerator-style top-level control.", "Scalar control arguments are present."],
        "action": "Keep scalar controls and return on s_axilite unless the task explicitly requires another control protocol.",
        "expected_signal": "Interface validation remains stable while internal QoR changes are isolated.",
        "contraindications": ["Do not switch ap_ctrl_none on a transactional kernel.", "Do not alter top-level ABI in optimize mode."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#multi-m-axi-bundles",
        "tags": ["interface", "s_axilite", "return", "control"],
    },
    {
        "id": "hlsgen.failure_triage.noop_reject",
        "family": "failure_triage",
        "preconditions": ["A candidate preserves public correctness but Q_HW does not improve.", "The action contract is no-op or unrelated to the bottleneck."],
        "action": "Record the action as a negative case and choose a different measured bottleneck rather than repeating it.",
        "expected_signal": "Subsequent retrieval avoids wasting API tokens on repeated no-op changes.",
        "contraindications": ["Do not ban the whole optimization family.", "Only reject the measured action under compatible structure and target."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#report-driven-checks",
        "tags": ["failure_triage", "noop", "q_hw_rejected", "history"],
    },
    {
        "id": "hlsgen.failure_triage.compile_first",
        "family": "failure_triage",
        "preconditions": ["A candidate fails CSim compile or synthesis compile.", "The previous best was valid."],
        "action": "Diagnose the compile-stage error before proposing any QoR optimization.",
        "expected_signal": "The next candidate restores CSim/Synth pass before Q_HW selection.",
        "contraindications": ["Do not accept a QoR claim from a compile-failing candidate.", "Do not inspect hidden or evaluator artifacts for the fix."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#optimization-discipline",
        "tags": ["failure_triage", "compile_error", "csim", "synth"],
    },
    {
        "id": "hlsgen.report_driven.clock_adjusted_latency",
        "family": "report_driven",
        "preconditions": ["A candidate improves cycle latency but worsens estimated clock.", "The scoring target uses hardware time or Q_HW."],
        "action": "Compare max(target_clock, estimated_clock) times latency before accepting the candidate.",
        "expected_signal": "Candidates with lower cycles but worse actual time are rejected.",
        "contraindications": ["Do not use cycles alone as acceptance evidence.", "Do not ignore frequency gate failures."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#report-driven-checks",
        "tags": ["report_driven", "clock", "latency", "q_hw", "frequency"],
    },
    {
        "id": "hlsgen.report_driven.one_family_budget",
        "family": "report_driven",
        "preconditions": ["Token budget or credit budget is constrained.", "Multiple speculative actions are possible."],
        "action": "Apply at most one optimization family per candidate and measure before asking for another candidate.",
        "expected_signal": "Token and synthesis budget are spent on attributable changes.",
        "contraindications": ["Do not stack pipeline, unroll, partition, and dataflow in one unmeasured edit.", "Do not repeat rejected actions from history."],
        "source": "third_party/hls-generator/references/hls-optimization-patterns.md#optimization-discipline",
        "tags": ["report_driven", "budget", "token", "single_action", "credits"],
    },
    {
        "id": "hlsgen.loop_tripcount.bound_annotation",
        "family": "loop_tripcount",
        "preconditions": ["A loop bound is data-dependent but bounded by task constants.", "The report lacks useful latency estimates."],
        "action": "Add LOOP_TRIPCOUNT only as reporting guidance; do not treat it as a performance optimization by itself.",
        "expected_signal": "Reports become more interpretable while synthesized hardware behavior remains unchanged.",
        "contraindications": ["Do not count tripcount annotation as Q_HW improvement.", "Do not invent bounds not present in source or task contract."],
        "source": "third_party/hls-generator/references/hls-modeling-strategy.md#loop-bounds-and-trip-counts",
        "tags": ["loop_tripcount", "report", "bound", "diagnostic"],
    },
    {
        "id": "hlsgen.inline.hotspot_only",
        "family": "inline",
        "preconditions": ["A small helper function is on the measured critical path.", "Inlining exposes pipeline or constant-propagation opportunities."],
        "action": "Inline only the measured hotspot helper, then synthesize to verify schedule and resource effects.",
        "expected_signal": "Function overhead or scheduling barriers fall without widespread code growth.",
        "contraindications": ["Do not recursively inline a whole helper tree.", "Do not inline large functions that hide memory stages."],
        "source": "third_party/hls-generator/references/hls-project-structure-patterns.md#hotspot-file-organization",
        "tags": ["inline", "helper", "hotspot", "pipeline"],
    },
    {
        "id": "hlsgen.source_restructure.preserve_top_abi",
        "family": "source_restructure",
        "preconditions": ["A candidate restructures source around helper functions or local buffers.", "The task is optimize mode with fixed public TB."],
        "action": "Preserve the top function signature, header contract, and public testbench-visible behavior during any source restructure.",
        "expected_signal": "Interface and CSim gates remain pass while QoR evidence changes.",
        "contraindications": ["Do not change top arguments or header APIs.", "Do not import reference or evaluator-only code."],
        "source": "third_party/hls-generator/references/hls-project-structure-patterns.md#helper-header-boundaries",
        "tags": ["source_restructure", "top_function", "abi", "public_only"],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-path",
        type=Path,
        default=Path("fpt26-agent-v3/agent/knowledge_assets/hls_generator_seeds.json"),
    )
    parser.add_argument(
        "--case-path",
        type=Path,
        default=Path("fpt26-agent-v3/agent/knowledge_assets/verified_cases.json"),
    )
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument(
        "--smoke-path",
        type=Path,
        default=Path("tasks/generated/public_hls_tasks_smoke.json"),
    )
    args = parser.parse_args()

    seeds = _load_records(args.seed_path)
    by_id = {record["id"]: record for record in seeds}
    for record in EXTRA_SEED_RULES:
        merged = {
            "kind": "rule",
            "confidence": "medium",
            "vitis_version": "2022.2+",
            "status": "unverified_seed",
            **record,
        }
        by_id[merged["id"]] = merged
    seed_records = [by_id[key] for key in sorted(by_id)]
    _validate(seed_records)
    _write(args.seed_path, seed_records)

    cases = _load_records(args.case_path)
    case_by_id = {record["id"]: record for record in cases}
    for report in sorted(args.runs_root.glob("**/submission/*/run_report.json")):
        for entry in curate_submission_report(report):
            case_by_id[entry.id] = _entry_to_record(entry)
    if args.smoke_path.is_file():
        for record in _smoke_failure_cases(args.smoke_path):
            case_by_id[record["id"]] = record
    case_records = [case_by_id[key] for key in sorted(case_by_id)]
    _validate(case_records)
    _write(args.case_path, case_records)

    print(
        json.dumps(
            {
                "seed_count": len(seed_records),
                "case_count": len(case_records),
                "case_kinds": _counts(record["kind"] for record in case_records),
                "seed_families": _counts(record["family"] for record in seed_records),
                "case_families": _counts(record["family"] for record in case_records),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _load_records(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return list(raw.get("entries") or [])


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {"schema_version": KNOWLEDGE_SCHEMA_VERSION, "entries": records},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _validate(records: list[dict[str, Any]]) -> None:
    seen = set()
    for record in records:
        entry = KnowledgeEntry.from_dict(record)
        if entry.id in seen:
            raise ValueError(f"duplicate knowledge id: {entry.id}")
        seen.add(entry.id)


def _entry_to_record(entry: KnowledgeEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "kind": entry.kind,
        "family": entry.family,
        "preconditions": list(entry.preconditions),
        "action": entry.action,
        "expected_signal": entry.expected_signal,
        "contraindications": list(entry.contraindications),
        "source": entry.source,
        "confidence": entry.confidence,
        "vitis_version": entry.vitis_version,
        "status": entry.status,
        "tags": list(entry.tags),
        "evidence": dict(entry.evidence),
    }


def _smoke_failure_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for item in raw.get("results") or []:
        if item.get("passed") is True:
            continue
        task_id = str(item.get("task_id") or "").strip()
        if not task_id:
            continue
        phase = (
            item.get("csim_phase")
            if item.get("csim_ok") is not True
            else item.get("synth_phase")
        )
        family = _family_from_smoke(item)
        records.append(
            {
                "id": f"submission.public_hls_smoke.{task_id}.negative",
                "kind": "failure_case",
                "family": family,
                "preconditions": [
                    f"Public imported HLS task {task_id} was smoke-tested with Vitis 2025.2.",
                    "The candidate failed before it could become a usable validation task.",
                ],
                "action": "Do not count or retrieve this public import candidate as a validated task until its public CSim/Synth failure is fixed.",
                "expected_signal": f"Avoids repeating a public smoke failure at phase {phase}.",
                "contraindications": [
                    "This does not reject the original upstream example permanently.",
                    "A repaired public-only adapter must rerun CSim and Synth before counting.",
                ],
                "source": f"submission:public_hls_smoke:{task_id}",
                "confidence": "high",
                "vitis_version": "2025.2",
                "status": "verified_failure",
                "tags": [
                    family,
                    "public_hls_import",
                    "csim_synth_smoke",
                    "q_hw_rejected",
                    "measured",
                ],
                "evidence": {
                    "observed_failure": True,
                    "stage": "public_hls_smoke",
                    "failure_category": str(phase),
                    "csim_ok": item.get("csim_ok") is True,
                    "synth_ok": item.get("synth_ok") is True,
                    "task_id": task_id,
                    "source": item.get("source"),
                    "source_path": item.get("source_path"),
                    "target_part": "xcu55c-fsvh2892-2L-e",
                },
            }
        )
    return records


def _family_from_smoke(item: dict[str, Any]) -> str:
    text = " ".join(
        str(item.get(key) or "").lower()
        for key in ("task_id", "source_path", "top_function", "csim_phase", "synth_phase")
    )
    if any(token in text for token in ("stream", "fifo", "axis")):
        return "stream_fifo"
    if any(token in text for token in ("fft", "fir", "float", "fixed", "sqrt")):
        return "math_kernel"
    if any(token in text for token in ("pointer", "axi", "memory", "m_axi")):
        return "interface"
    if any(token in text for token in ("pipeline", "loop")):
        return "pipeline"
    return "failure_triage"


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


if __name__ == "__main__":
    raise SystemExit(main())
