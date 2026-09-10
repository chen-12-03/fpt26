#!/usr/bin/env python3
"""Build a non-overlapping, moderate-difficulty 150-task Track-A candidate set.

This builder intentionally writes a new corpus instead of mutating the frozen
``tasks/track_a_150`` evidence.  It treats a near-duplicate cluster as the
experimental unit, assigns every selected family to exactly one category, and
emits task packages compatible with the submission-side Task loader.

The output is a *candidate* corpus.  Static/package validation is performed
here; Vitis CSim/Synth/CoSim acceptance and independent hidden-test hardening
remain separate, mandatory gates before the corpus can be frozen for a paper.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 in the frozen image.
    import tomli as tomllib

from build_track_a_150 import (
    PERFORMANCE_PRAGMA,
    _code_generation_stub,
    _ensure_contract_header,
    _inject_early_return,
    _mutate_literal,
    sha256_text,
)


U55C_PART = "xcu55c-fsvh2892-2L-e"
CLOCK_NS = 5.0
TASKS_PER_CATEGORY = 25
# This is the strictest threshold at which the current 196-package source pool
# still contains 150 eligible, moderate-difficulty kernel families.  Lowering
# it to 0.85 leaves fewer such families and would force genuinely extreme
# tasks into the corpus merely to satisfy the headline count.
NEAR_DUPLICATE_THRESHOLD = 0.87
HLS_EVAL_URL = "https://github.com/sharc-lab/hls-eval"

CATEGORIES: tuple[tuple[str, str, str, bool], ...] = (
    ("code_generation", "generate", "compile_fail", False),
    ("compile_repair", "repair", "compile_fail", False),
    ("synthesis_repair", "synth_fix", "synth_fail", False),
    ("functional_repair", "repair", "csim_fail", False),
    ("structural_cosim_repair", "repair", "cosim_fail", True),
    ("qor_optimization", "optimize", "valid_baseline", False),
)

_KEYWORDS = {
    "alignas",
    "auto",
    "bool",
    "break",
    "case",
    "char",
    "class",
    "const",
    "continue",
    "default",
    "do",
    "double",
    "else",
    "enum",
    "extern",
    "float",
    "for",
    "if",
    "int",
    "long",
    "namespace",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "struct",
    "switch",
    "template",
    "typedef",
    "typename",
    "union",
    "unsigned",
    "using",
    "void",
    "volatile",
    "while",
}

_SOURCE_CAPS: dict[str, dict[str, int]] = {
    "structural_cosim_repair": {
        # Structural CoSim requires a self-checking RTL-capable testbench.
        # Most converted PolyBench/MachSuite benches only print outputs, so
        # prefer the empirically stronger AMD examples for this category.
        "amd_intro": 23,
        "amd_accel": 5,
        "polybench": 6,
        "machsuite": 6,
        "chstone": 4,
        "c2hlsc": 4,
        "pp4fpga": 2,
        "flowgnn": 2,
    },
    "code_generation": {
        "polybench": 10,
        "machsuite": 8,
        "chstone": 5,
        "c2hlsc": 4,
        "pp4fpga": 3,
        "rosetta": 3,
    },
    "qor_optimization": {
        "amd_intro": 10,
        "amd_accel": 8,
        "polybench": 9,
        "machsuite": 6,
        "c2hlsc": 4,
        "pp4fpga": 3,
        "chstone": 3,
        "rosetta": 2,
    },
}

# Empirically rejected by fresh Vitis 2025.2 U55C acceptance: either the
# derived starter cannot synthesize or one side lacks a scoreable latency.
_QOR_REJECTED_SOURCES = {
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_merge_round_robin",
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_split_round_robin",
    "amd_accel__host_xrt_p2p_fpga2fpga_xrt_src_increment",
    "amd_accel__host_xrt_p2p_simple_xrt_src_adder",
    "machsuite__sort_merge",
    "machsuite__md_grid",
    "machsuite__kmp_kmp",
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_merge_load_balance",
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_split_load_balance",
    "machsuite__bfs_bulk",
    "machsuite__bfs_queue",
    "amd_accel__host_xrt_host_memory_simple_xrt_src_kernel",
    "amd_accel__host_xrt_host_memory_copy_kernel_xrt_src_copy_kernel",
    "machsuite__nw_nw",
    "machsuite__fft_strided",
    "amd_accel__host_xrt_data_transfer_xrt_src_dummy_kernel",
    "pp4fpga__parallel_merge_sort",
    "amd_accel__host_xrt_host_memory_copy_kernel_xrt_src_krnl_vadd",
    "amd_accel__host_xrt_host_memory_copy_buffer_xrt_src_krnl_vadd",
    "machsuite__spmv_crs",
    "chstone__dfdiv",
}

_STRUCTURAL_ACCEPTED_SOURCES = {
    "amd_intro__array_array_partition_block_cyclic",
    "amd_intro__interface_register_using_axi_lite_with_user_defined_offset",
    "amd_intro__interface_aggregation_disaggregation_aggregation_of_m_axi_ports",
    "amd_intro__interface_aggregation_disaggregation_aggregation_of_struct",
    "amd_intro__interface_aggregation_disaggregation_disaggregation_of_axis_port",
    "amd_intro__interface_memory_burst_rw",
    "amd_intro__interface_memory_coefficient_filter",
    "amd_intro__interface_memory_max_widen_port_width",
    "amd_intro__interface_memory_ram_uram",
    "amd_intro__interface_memory_using_axi_master",
    "amd_intro__interface_streaming_using_array_of_streams",
    "amd_intro__interface_streaming_using_axi_stream_with_side_channel_data",
    "amd_intro__misc_initialization_and_reset_static_array_ram",
    "amd_intro__misc_initialization_and_reset_static_array_rom",
    "amd_intro__misc_initialization_and_reset_static_array_of_struct_with_array_ram",
    "amd_intro__modeling_using_float_and_double",
    "amd_intro__modeling_cpp_templates_for_multiple_instances",
    "amd_intro__task_level_parallelism_control_driven_directio_ap_hs",
    "amd_intro__task_level_parallelism_data_driven_simple_data_driven",
    "amd_intro__task_level_parallelism_data_driven_using_axilite_with_directio",
    "amd_intro__task_level_parallelism_data_driven_using_directio_hs_in_tasks",
    "amd_intro__task_level_parallelism_data_driven_using_directio_none_in_tasks",
    "chstone__df_countLeadingZeros64",
    "chstone__df_countLeadingZeros32",
    "chstone__df_mul64To128",
}

# Reference anchors that fail the U55C/Vitis 2025.2 synthesis gate.  They
# cannot define a reliable synthesis-repair task even though the injected
# starter failure itself is deterministic.
_SYNTHESIS_REJECTED_SOURCES = {
    "amd_accel__performance_host_global_bandwidth_src_kernel",
    "amd_accel__performance_p2p_fpga2fpga_bandwidth_src_bandwidth",
    "c2hlsc__shift_rows",
    "flowgnn__fgnn_linear_input_stationary",
    "pp4fpga__parallel_merge_sort",
}

_REDISTRIBUTION_REPLACEMENTS = {
    # FlowGNN has no repository license.  Preserve the otherwise frozen
    # allocation and replace only those two selected families with compact,
    # self-checking kernels from the BSD-3-Clause Rosetta suite.
    "flowgnn__fgnn_linear": "rosetta__spam_filter__computeGradient",
    "flowgnn__fgnn_linear_output_stationary": "rosetta__spam_filter__dotProduct",
}

_REFERENCE_NORMALIZATIONS = {
    "c2hlsc__des": "fix_des_round_key_pointer_indexing",
}

# Category-specific failures for the early-return functional mutant: either
# the public C test does not observe the changed output or the derived starter
# no longer synthesizes on U55C.
_FUNCTIONAL_REJECTED_SOURCES = {
    "amd_accel__host_xrt_data_transfer_xrt_src_dummy_kernel",
    "amd_accel__host_xrt_p2p_fpga2fpga_xrt_src_increment",
    "amd_intro__dsp_fir_decimator",
    "amd_intro__interface_aggregation_disaggregation_aggregation_of_nested_structs",
    "amd_intro__interface_memory_manual_burst_manual_burst_with_conditionals",
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_merge_round_robin",
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_merge_load_balance",
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_split_round_robin",
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_split_load_balance",
    "amd_intro__task_level_parallelism_control_driven_channels_using_fifos",
    "amd_intro__task_level_parallelism_control_driven_channels_using_stream_of_blocks",
    "amd_intro__task_level_parallelism_data_driven_using_maxi_in_tasks",
    "amd_intro__task_level_parallelism_control_driven_patterns_using_stream_as_sync",
    "polybench__cholesky",
    "polybench__doitgen",
    "polybench__floyd_warshall",
    "polybench__jacobi_1d",
    "polybench__mvt",
    "polybench__seidel_2d",
    "polybench__trmm",
    "polybench__trisolv",
}

_STRUCTURAL_REJECTED_SOURCES = {
    "amd_accel__host_xrt_copy_buffer_xrt_src_vector_addition",
    "amd_accel__host_xrt_data_transfer_xrt_src_dummy_kernel",
    "amd_accel__host_xrt_multiple_cus_asymmetrical_xrt_src_vadd",
    "amd_accel__host_xrt_p2p_fpga2fpga_xrt_src_increment",
    "amd_accel__host_xrt_p2p_simple_xrt_src_adder",
    "amd_accel__performance_axi_burst_performance_src_test_kernel_maxi_512bit_6",
    "amd_accel__sys_opt_kernel_swap_src_krnl_vadd",
    "amd_accel__sys_opt_kernel_swap_src_krnl_vmul",
    "amd_accel__sys_opt_multiple_process_src_krnl_vadd",
    "amd_intro__dsp_fir_decimator",
    "amd_intro__interface_aggregation_disaggregation_struct_ii_issue",
    "amd_intro__interface_aggregation_disaggregation_aggregation_of_nested_structs",
    "amd_intro__interface_memory_aliasing_axi_master_ports",
    "amd_intro__interface_memory_ecc_flags",
    "amd_intro__interface_memory_memory_bottleneck_modified",
    "amd_intro__interface_memory_memory_bottleneck_original",
    "amd_intro__interface_memory_rom_lookup_table_math",
    "amd_intro__misc_rtl_as_blackbox",
    "amd_intro__modeling_free_running_kernel_remerge_ii4to1",
    "amd_intro__modeling_using_arbitrary_precision_arith",
    "amd_intro__modeling_pointers_using_double",
    "amd_intro__modeling_pointers_multiple_pointers",
    "amd_intro__modeling_pointers_basic_arithmetic",
    "amd_intro__modeling_pointers_stream_better",
    "amd_intro__modeling_using_cpp_templates",
    "amd_intro__pipelining_functions_function_instantiate",
    "amd_intro__pipelining_loops_imperfect_loop",
    "amd_intro__pipelining_loops_perfect_loop",
    "amd_intro__pipelining_loops_pipelined_loop",
    "amd_intro__pipelining_loops_using_free_running_pipeline",
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_merge_round_robin",
    "amd_intro__task_level_parallelism_control_driven_channels_merge_split_split_round_robin",
    "amd_intro__task_level_parallelism_control_driven_channels_simple_fifos",
    "amd_intro__task_level_parallelism_control_driven_channels_using_fifos",
    "amd_intro__task_level_parallelism_control_driven_channels_using_stream_of_blocks",
    "amd_intro__task_level_parallelism_data_driven_using_maxi_in_tasks",
    "c2hlsc__overlapping",
    "machsuite__gemm_blocked",
    "machsuite__gemm_ncubed",
    "machsuite__md_knn",
    "machsuite__stencil_stencil2d",
    "machsuite__stencil_stencil3d",
    "machsuite__viterbi_viterbi",
    "polybench__3mm",
    "polybench__2mm",
    "polybench__bicg",
    "polybench__correlation",
    "polybench__covariance",
    "polybench__durbin",
    "polybench__fdtd_2d",
    "polybench__gemm",
    "polybench__gemver",
    "polybench__gesummv",
    "polybench__gramschmidt",
    "polybench__heat_3d",
    "polybench__ludcmp",
    "polybench__lu",
    "polybench__nussinov",
    "polybench__symm",
    "polybench__syr2k",
    "polybench__syrk",
    "pp4fpga__block_mm",
    "pp4fpga__parallel_merge_sort",
    "pp4fpga__pp4fpga_cordic",
}


@dataclass(frozen=True)
class Source:
    task_dir: Path
    spec: dict[str, Any]
    kernel: str
    public_tb: str
    description: str
    suite: str
    kernel_loc: int
    tb_loc: int
    source_difficulty: int
    top_called: bool
    public_check_signal: bool
    detailed_spec: bool
    loop_count: int
    structural_signal_count: int
    pragma_count: int
    normalized_hash: str
    shingles: frozenset[tuple[str, ...]]
    previously_completed: bool
    provenance: dict[str, str]

    @property
    def task_id(self) -> str:
        return self.task_dir.name


@dataclass(frozen=True)
class Family:
    family_id: str
    members: tuple[Source, ...]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _without_comments(value: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", " ", value, flags=re.DOTALL)


def _normalized_hash(value: str) -> str:
    return sha256_text("".join(_without_comments(value).split()))


def _token_shingles(value: str) -> frozenset[tuple[str, ...]]:
    text = _without_comments(value)
    text = re.sub(r'"(?:\\.|[^"\\])*"', "STR", text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", "CHR", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "NUM", text)
    tokens = re.findall(
        r"[A-Za-z_]\w*|==|!=|<=|>=|<<|>>|\+\+|--|&&|\|\||\S", text
    )
    normalized = [
        token
        if (
            re.fullmatch(r"[A-Za-z_]\w*", token) is None
            or token in _KEYWORDS
            or token.startswith(("ap_", "hls", "HLS"))
        )
        else "ID"
        for token in tokens
    ]
    if len(normalized) < 5:
        return frozenset({tuple(normalized)})
    return frozenset(
        tuple(normalized[index : index + 5])
        for index in range(len(normalized) - 4)
    )


def _jaccard(left: frozenset[Any], right: frozenset[Any]) -> float:
    return len(left & right) / max(1, len(left | right))


def _line_count(value: str) -> int:
    return sum(bool(line.strip()) for line in value.splitlines())


def _load_prior_completion(report: Path | None) -> set[str]:
    if report is None or not report.is_file():
        return set()
    payload = json.loads(report.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") or {}
    return {
        task_id
        for task_id, record in tasks.items()
        if isinstance(record, dict) and record.get("outcome") == "completed"
    }


def _provenance(task_dir: Path, spec: dict[str, Any], suite: str) -> dict[str, str]:
    raw = spec.get("provenance") or {}
    if raw.get("source_url") and raw.get("repo_commit") and raw.get("license"):
        return {
            "source_url": str(raw["source_url"]),
            "source_path": str(raw.get("source_path", "")),
            "repo_commit": str(raw["repo_commit"]),
            "license": str(raw["license"]),
            "status": "verified_in_source_package",
        }
    return {
        "source_url": f"{HLS_EVAL_URL}/tree/main/hls_eval_data/{suite}",
        "source_path": task_dir.name,
        "repo_commit": "LOCAL_SNAPSHOT_REQUIRES_UPSTREAM_MATCH",
        "license": "UPSTREAM_REVIEW_REQUIRED",
        "status": "candidate_only_requires_upstream_license_and_commit_audit",
    }


def _load_sources(source_root: Path, prior_report: Path | None) -> list[Source]:
    completed = _load_prior_completion(prior_report)
    sources: list[Source] = []
    for manifest in sorted(source_root.glob("*/task.toml")):
        task_dir = manifest.parent
        spec = tomllib.loads(manifest.read_text(encoding="utf-8"))
        kernel_path = task_dir / str(spec.get("kernel_file", ""))
        tb_path = task_dir / str(spec.get("public_tb", ""))
        top = str(spec.get("top", ""))
        if not kernel_path.is_file() or not tb_path.is_file() or not top:
            continue
        headers = spec.get("header_files", [])
        if not isinstance(headers, list) or not all(
            isinstance(name, str) and (task_dir / name).is_file() for name in headers
        ):
            continue
        kernel = kernel_path.read_text(encoding="utf-8", errors="replace")
        if task_dir.name == "c2hlsc__des":
            # The upstream function receives a pointer to one 16-round key
            # schedule.  ``key[idx]`` advances by an entire schedule and is
            # out of bounds after round zero; address the idx-th subkey within
            # the pointed-to schedule instead.  This deterministic repair is
            # applied before any category-specific starter fault is injected.
            old_round = "f(state[1], key[idx])"
            old_final = "f(state[1], key[15])"
            if kernel.count(old_round) != 1 or kernel.count(old_final) != 1:
                raise RuntimeError("c2hlsc__des normalization pattern mismatch")
            kernel = kernel.replace(old_round, "f(state[1], &(*key)[idx])")
            kernel = kernel.replace(old_final, "f(state[1], &(*key)[15])")
        public_tb = tb_path.read_text(encoding="utf-8", errors="replace")
        description_path = task_dir / "description.md"
        description = (
            description_path.read_text(encoding="utf-8", errors="replace")
            if description_path.is_file()
            else ""
        )
        suite = task_dir.name.split("__", 1)[0]
        clean = _without_comments(kernel)
        top_called = bool(
            re.search(rf"(?<![\w:]){re.escape(top)}\s*\(", public_tb)
        )
        public_check_signal = bool(
            re.search(
                r"assert|return\s+1|!=|==|PASS|FAIL|error|correct",
                public_tb,
                re.IGNORECASE,
            )
        )
        detailed_spec = len(description) >= 500 and bool(
            re.search(r"Complete Function Signature|Top-Level Function", description)
        )
        sources.append(
            Source(
                task_dir=task_dir,
                spec=spec,
                kernel=kernel,
                public_tb=public_tb,
                description=description,
                suite=suite,
                kernel_loc=_line_count(kernel),
                tb_loc=_line_count(public_tb),
                source_difficulty=int(spec.get("difficulty", 3)),
                top_called=top_called,
                public_check_signal=public_check_signal,
                detailed_spec=detailed_spec,
                loop_count=len(re.findall(r"\b(?:for|while)\s*\(", clean)),
                structural_signal_count=len(
                    re.findall(
                        r"hls::stream|DATAFLOW|axis|ap_(?:fifo|hs|none)",
                        kernel,
                        re.IGNORECASE,
                    )
                ),
                pragma_count=len(
                    re.findall(r"#\s*pragma\s+HLS", kernel, re.IGNORECASE)
                ),
                normalized_hash=_normalized_hash(kernel),
                shingles=_token_shingles(kernel),
                previously_completed=task_dir.name in completed,
                provenance=_provenance(task_dir, spec, suite),
            )
        )
    return sources


def _families(sources: list[Source], threshold: float) -> list[Family]:
    parent = list(range(len(sources)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left, right in itertools.combinations(range(len(sources)), 2):
        if _jaccard(sources[left].shingles, sources[right].shingles) >= threshold:
            union(left, right)

    grouped: dict[int, list[Source]] = defaultdict(list)
    for index, source in enumerate(sources):
        grouped[find(index)].append(source)

    result = []
    for members in grouped.values():
        ordered = tuple(sorted(members, key=lambda item: item.task_id))
        identity = "\n".join(item.normalized_hash for item in ordered)
        result.append(Family(sha256_text(identity), ordered))
    return sorted(result, key=lambda family: family.family_id)


def _moderate(source: Source) -> bool:
    # The upper bound admits two CHStone floating-point kernels at 252/261 LOC
    # and one AMD stencil example at 438 LOC after invalid anchors are removed.
    # All retain source difficulty 2/3; every difficulty-5 source remains out.
    return source.source_difficulty in {2, 3, 4} and 10 <= source.kernel_loc <= 450


def _quality(source: Source) -> tuple[Any, ...]:
    return (
        int(_moderate(source)),
        int(source.previously_completed),
        int(source.public_check_signal),
        int(source.top_called),
        -abs(source.kernel_loc - 60),
        source.task_id,
    )


def _eligible(category: str, source: Source) -> bool:
    # Difficulty moderation is a source-selection constraint, not a label
    # rewrite: selected kernels must already be difficulty 2--4 and remain
    # within a practical source-size range.
    if (
        not _moderate(source)
        or not source.top_called
        or source.task_id in _SYNTHESIS_REJECTED_SOURCES
    ):
        return False
    if category == "code_generation":
        return (
            source.detailed_spec
            and source.public_check_signal
            and 10 <= source.kernel_loc <= 140
        )
    if category == "structural_cosim_repair":
        # CoSim repair tasks are defined by a C/RTL behavioral mismatch.  The
        # source need not already contain a stream/dataflow construct; in fact,
        # compact conventional kernels yield more portable CoSim evidence than
        # vendor examples whose original testbench cannot drive RTL.
        return (
            source.task_id not in _STRUCTURAL_REJECTED_SOURCES
            and source.public_check_signal
        )
    if category == "qor_optimization":
        return (
            source.task_id not in _QOR_REJECTED_SOURCES
            and source.loop_count > 0
            and source.public_check_signal
        )
    if category == "functional_repair":
        return (
            source.task_id not in _FUNCTIONAL_REJECTED_SOURCES
            and source.public_check_signal
        )
    return True


def _category_rank(category: str, source: Source) -> tuple[Any, ...]:
    if category == "structural_cosim_repair":
        return (
            int(_moderate(source)),
            int(source.previously_completed),
            int(source.public_check_signal),
            int(source.top_called),
            int(source.task_id in _STRUCTURAL_ACCEPTED_SOURCES),
            int(source.structural_signal_count == 0),
            -source.structural_signal_count,
            -abs(source.kernel_loc - 60),
            source.task_id,
        )
    special = 0
    if category == "qor_optimization":
        special = source.loop_count + source.pragma_count
    elif category == "code_generation":
        special = len(source.description)
    return (*_quality(source), special)


def _pick(
    category: str,
    families: list[Family],
    used: set[str],
) -> list[tuple[Family, Source]]:
    candidates: list[tuple[tuple[Any, ...], Family, Source]] = []
    for family in families:
        if family.family_id in used:
            continue
        eligible = [member for member in family.members if _eligible(category, member)]
        if not eligible:
            continue
        source = max(eligible, key=lambda item: _category_rank(category, item))
        candidates.append((_category_rank(category, source), family, source))

    caps = _SOURCE_CAPS.get(category, {})
    counts: Counter[str] = Counter()
    chosen: list[tuple[Family, Source]] = []
    for _, family, source in sorted(candidates, key=lambda item: item[0], reverse=True):
        if counts[source.suite] >= caps.get(source.suite, TASKS_PER_CATEGORY):
            continue
        chosen.append((family, source))
        counts[source.suite] += 1
        used.add(family.family_id)
        if len(chosen) == TASKS_PER_CATEGORY:
            return chosen
    raise RuntimeError(
        f"not enough unused source families for {category}: {len(chosen)}/"
        f"{TASKS_PER_CATEGORY}; available_candidates={len(candidates)}"
    )


def _allocation(families: list[Family]) -> dict[str, list[tuple[Family, Source]]]:
    # Constrained categories go first.  The three generic repair categories
    # consume the remaining families only after structural, generation and QoR
    # coverage has been secured.
    order = (
        "structural_cosim_repair",
        "code_generation",
        "qor_optimization",
        "functional_repair",
        "synthesis_repair",
        "compile_repair",
    )
    used: set[str] = set()
    allocation = {category: _pick(category, families, used) for category in order}
    by_task_id = {
        source.task_id: (family, source)
        for family in families
        for source in family.members
    }
    selected_family_ids = {
        family.family_id
        for selected in allocation.values()
        for family, _ in selected
    }
    synthesis = allocation["synthesis_repair"]
    for victim, replacement in _REDISTRIBUTION_REPLACEMENTS.items():
        victim_index = next(
            index
            for index, (_, source) in enumerate(synthesis)
            if source.task_id == victim
        )
        replacement_pair = by_task_id[replacement]
        replacement_family, replacement_source = replacement_pair
        if replacement_family.family_id in selected_family_ids:
            raise RuntimeError(f"replacement family already selected: {replacement}")
        selected_family_ids.remove(synthesis[victim_index][0].family_id)
        selected_family_ids.add(replacement_family.family_id)
        synthesis[victim_index] = (replacement_family, replacement_source)
    return allocation


def _top_body(source: str, top: str) -> tuple[int, str]:
    clean = re.sub(
        r"//[^\n]*|/\*.*?\*/",
        lambda match: "".join(
            "\n" if char == "\n" else " " for char in match.group(0)
        ),
        source,
        flags=re.DOTALL,
    )
    match = re.search(rf"\b{re.escape(top)}\s*\(", clean)
    if match is None:
        raise RuntimeError(f"cannot locate top function: {top}")
    open_paren = clean.find("(", match.start())
    depth = 0
    close_paren = None
    for index in range(open_paren, len(clean)):
        if clean[index] == "(":
            depth += 1
        elif clean[index] == ")":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
    if close_paren is None:
        raise RuntimeError(f"unbalanced top signature: {top}")
    body = clean.find("{", close_paren)
    if body < 0:
        raise RuntimeError(f"cannot locate top body: {top}")
    start = match.start()
    while start > 0 and clean[start - 1] not in ";{}":
        start -= 1
    prefix = clean[start : match.start()].strip()
    return body, "return;" if re.search(r"\bvoid\s*$", prefix) else "return {};"


def _inject_at_top(source: str, top: str, lines: str) -> str:
    body, _ = _top_body(source, top)
    return source[: body + 1] + "\n" + lines + "\n" + source[body + 1 :]


def _disable_braced_loop_pipelines(source: str) -> tuple[str, int]:
    """Insert a local PIPELINE-off directive into every braced loop."""

    clean = re.sub(
        r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
        lambda match: "".join(
            "\n" if char == "\n" else " " for char in match.group(0)
        ),
        source,
        flags=re.DOTALL,
    )
    insertions: list[int] = []
    for match in re.finditer(r"\b(?:for|while)\s*\(", clean):
        opening = clean.find("(", match.start(), match.end())
        depth = 0
        closing = None
        for index in range(opening, len(clean)):
            if clean[index] == "(":
                depth += 1
            elif clean[index] == ")":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None:
            continue
        body = closing + 1
        while body < len(clean) and clean[body].isspace():
            body += 1
        if body < len(clean) and clean[body] == "{":
            insertions.append(body + 1)
    mutated = source
    for offset in reversed(sorted(set(insertions))):
        mutated = (
            mutated[:offset]
            + "\n#pragma HLS PIPELINE off\n"
            + mutated[offset:]
        )
    return mutated, len(set(insertions))


def _baseline(category: str, source: Source) -> tuple[str, str]:
    top = str(source.spec["top"])
    if category == "code_generation":
        return _code_generation_stub(source.kernel, top), "signature_only_generation_stub"
    if category == "compile_repair":
        return (
            _inject_at_top(source.kernel, top, "  int track_a_compile_probe = ;"),
            "top_body_missing_initializer_expression",
        )
    if category == "synthesis_repair":
        return (
            _inject_at_top(
                source.kernel,
                top,
                "#ifdef __SYNTHESIS__\n"
                "  undefined_synthesis_type synthesis_probe;\n"
                "#endif",
            ),
            "synthesis_only_undefined_local_type",
        )
    if category == "functional_repair":
        # A mutation selected from the raw source can land in a copyright
        # comment and leave executable semantics unchanged.  A top-body early
        # return is interface-preserving, synthesizable, and must be detected
        # by a meaningful functional testbench; the acceptance pass verifies
        # both the CSim failure and successful synthesis.
        return _inject_early_return(source.kernel, top, 0)
    if category == "structural_cosim_repair":
        mutated, mutation = _inject_early_return(source.kernel, top, 0)
        return (
            "#ifndef __SYNTHESIS__\n"
            + source.kernel
            + "\n#else\n"
            + mutated
            + "\n#endif\n",
            "synthesis_only_" + mutation,
        )
    if category == "qor_optimization":
        # QoR tasks begin from the acquired, functionally correct source.  We
        # intentionally avoid inserting synthetic delay loops: doing so would
        # turn the task into artifact deletion rather than HLS optimization.
        return source.kernel, "upstream_valid_baseline:no_artificial_degradation"
    raise AssertionError(category)


def _difficulty(category: str, source: Source) -> int:
    if category == "code_generation":
        return 2 if source.kernel_loc <= 30 else 3 if source.kernel_loc <= 80 else 4
    if category in {"qor_optimization", "structural_cosim_repair"}:
        complexity = source.loop_count + source.structural_signal_count
        return 4 if source.kernel_loc > 140 or complexity >= 10 else 3
    return 2 if source.kernel_loc <= 35 else 3 if source.kernel_loc <= 140 else 4


def _copy_public_assets(source: Source, destination: Path) -> None:
    excluded = {
        "task.toml",
        "description.md",
        str(source.spec["kernel_file"]),
    }
    for path in source.task_dir.iterdir():
        if (
            path.is_file()
            and path.name not in excluded
            and not path.name.endswith(":Zone.Identifier")
        ):
            shutil.copy2(path, destination / path.name)


def _copy_hidden_assets(source: Source, destination: Path) -> tuple[str, str]:
    hidden_name = str(source.spec.get("hidden_tb", source.spec["public_tb"]))
    source_hidden = source.task_dir / "hidden"
    hidden_status = "source_hidden_testbench"
    if source_hidden.is_dir():
        for path in source_hidden.iterdir():
            if path.is_file() and not path.name.endswith(":Zone.Identifier"):
                shutil.copy2(path, destination / path.name)
    if not (destination / hidden_name).is_file():
        shutil.copy2(source.task_dir / str(source.spec["public_tb"]), destination / hidden_name)
        hidden_status = "public_testbench_fallback_requires_hardening"
    for path in source.task_dir.iterdir():
        if (
            path.is_file()
            and not path.name.endswith(":Zone.Identifier")
            and path.suffix.lower() in {".data", ".dat", ".txt"}
        ):
            shutil.copy2(path, destination / path.name)
    return hidden_name, hidden_status


def _description(category: str, source: Source, expected: str) -> str:
    instructions = {
        "code_generation": "Implement the complete HLS kernel from the specification.",
        "compile_repair": "Repair the C/C++ compilation failure without changing the interface.",
        "synthesis_repair": "Repair the HLS synthesis failure while preserving behavior.",
        "functional_repair": "Repair the functional defect so all tests pass.",
        "structural_cosim_repair": "Repair the C/RTL CoSim mismatch while preserving the public C model.",
        "qor_optimization": "Improve latency/throughput and area without changing functionality.",
    }[category]
    original = source.description.strip() or (
        f"Preserve the behavior and interface of top-level function `{source.spec['top']}`."
    )
    return (
        f"# Track-A v2: {category}\n\n"
        f"{instructions}\n\n"
        "Only the kernel source may be changed. File names, headers, data types, "
        "top-level interfaces, and testbenches are fixed. Target Alveo U55C with "
        "Vitis 2025.2 and a minimum frequency of 100 MHz.\n\n"
        f"Expected initial state: `{expected}`.\n\n"
        "## Kernel specification\n\n"
        + original
        + "\n"
    )


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _task_toml(
    *,
    task_id: str,
    category: str,
    task_type: str,
    expected: str,
    requires_cosim: bool,
    difficulty: int,
    source: Source,
    family: Family,
    hidden_tb: str,
    mutation: str,
) -> str:
    headers = ", ".join(
        _toml_string(str(name)) for name in source.spec.get("header_files", [])
    )
    provenance = source.provenance
    return (
        f"task_id = {_toml_string(task_id)}\n"
        f"task_type = {_toml_string(task_type)}\n"
        f"track_a_category = {_toml_string(category)}\n"
        f"difficulty = {difficulty}\n"
        f"top = {_toml_string(str(source.spec['top']))}\n"
        f"kernel_file = {_toml_string(str(source.spec['kernel_file']))}\n"
        f"header_files = [{headers}]\n"
        f"public_tb = {_toml_string(str(source.spec['public_tb']))}\n"
        f"hidden_tb = {_toml_string(hidden_tb)}\n"
        "budget = 60\n"
        f"requires_cosim = {'true' if requires_cosim else 'false'}\n"
        f"initial_condition = {_toml_string('Track-A v2 ' + category + '; baseline=' + expected)}\n"
        f"expected_baseline_state = {_toml_string(expected)}\n"
        f"fault_derivation = {_toml_string(mutation)}\n"
        f"kernel_family_id = {_toml_string(family.family_id)}\n"
        f"source_task_id = {_toml_string(source.task_id)}\n"
        f"source_url = {_toml_string(provenance['source_url'])}\n"
        f"source_path = {_toml_string(provenance['source_path'])}\n"
        f"repo_commit = {_toml_string(provenance['repo_commit'])}\n"
        f"license = {_toml_string(provenance['license'])}\n"
        f"source_sha256 = {_toml_string(_sha256_bytes(source.kernel.encode('utf-8')))}\n\n"
        f"reference_normalization = {_toml_string(_REFERENCE_NORMALIZATIONS.get(source.task_id, 'none'))}\n\n"
        "[target]\n"
        f"part = {_toml_string(U55C_PART)}\n"
        f"clock_ns = {CLOCK_NS:.3f}\n"
        "minimum_frequency_mhz = 100.0\n"
    )


def _safe_public_name(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return bool(
        name
        and not path.is_absolute()
        and ".." not in path.parts
        and not ({"hidden", "reference"} & {part.lower() for part in path.parts})
    )


def _validate_static(output_root: Path) -> dict[str, Any]:
    manifests = sorted(output_root.glob("*/task.toml"))
    errors: list[str] = []
    categories: Counter[str] = Counter()
    difficulties: Counter[int] = Counter()
    families: Counter[str] = Counter()
    weak_public_testbenches: list[str] = []
    for manifest in manifests:
        try:
            spec = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"{manifest.parent.name}: invalid task.toml: {exc}")
            continue
        categories[str(spec.get("track_a_category"))] += 1
        difficulties[int(spec.get("difficulty", 0))] += 1
        families[str(spec.get("kernel_family_id"))] += 1
        names = [
            str(spec.get("kernel_file", "")),
            str(spec.get("public_tb", "")),
            *[str(name) for name in spec.get("header_files", [])],
        ]
        for name in names:
            if not _safe_public_name(name) or not (manifest.parent / name).is_file():
                errors.append(f"{manifest.parent.name}: invalid public file {name!r}")
        hidden_name = str(spec.get("hidden_tb", ""))
        if not _safe_public_name(hidden_name) or not (
            manifest.parent / "hidden" / hidden_name
        ).is_file():
            errors.append(f"{manifest.parent.name}: invalid hidden testbench")
        if not (
            manifest.parent / "reference" / str(spec.get("kernel_file", ""))
        ).is_file():
            errors.append(f"{manifest.parent.name}: missing reference kernel")
        public_tb = manifest.parent / str(spec.get("public_tb", ""))
        if public_tb.is_file():
            text = public_tb.read_text(encoding="utf-8", errors="replace")
            top = str(spec.get("top", ""))
            if not re.search(rf"(?<![\w:]){re.escape(top)}\s*\(", text):
                errors.append(f"{manifest.parent.name}: public TB does not call top")
            if not re.search(
                r"assert|return\s+1|!=|==|PASS|FAIL|error|correct",
                text,
                re.IGNORECASE,
            ):
                weak_public_testbenches.append(manifest.parent.name)
    expected_counts = Counter({category: TASKS_PER_CATEGORY for category, *_ in CATEGORIES})
    if categories != expected_counts:
        errors.append(f"category counts: {dict(categories)}")
    duplicates = sorted(family for family, count in families.items() if count != 1)
    if duplicates:
        errors.append(f"non-unique family ids: {duplicates}")
    if len(manifests) != len(CATEGORIES) * TASKS_PER_CATEGORY:
        errors.append(f"task count: {len(manifests)}")
    if set(difficulties) - {2, 3, 4}:
        errors.append(f"extreme/invalid difficulties: {dict(difficulties)}")
    return {
        "ok": not errors,
        "errors": errors,
        "task_count": len(manifests),
        "category_counts": dict(sorted(categories.items())),
        "difficulty_counts": {str(key): value for key, value in sorted(difficulties.items())},
        "unique_kernel_family_count": len(families),
        "weak_public_testbench_count": len(weak_public_testbenches),
        "weak_public_testbench_task_ids": weak_public_testbenches,
    }


def build(
    source_root: Path,
    output_root: Path,
    prior_report: Path | None,
    threshold: float,
) -> dict[str, Any]:
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty corpus: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    sources = _load_sources(source_root, prior_report)
    families = _families(sources, threshold)
    allocation = _allocation(families)
    manifest_tasks: list[dict[str, Any]] = []

    category_meta = {category: (task_type, expected, cosim) for category, task_type, expected, cosim in CATEGORIES}
    for category, selected in allocation.items():
        task_type, expected, requires_cosim = category_meta[category]
        for index, (family, source) in enumerate(selected, start=1):
            task_id = f"{category}__{index:02d}__{source.task_id}"
            task_dir = output_root / task_id
            (task_dir / "hidden").mkdir(parents=True)
            (task_dir / "reference").mkdir()
            _copy_public_assets(source, task_dir)
            hidden_tb, hidden_status = _copy_hidden_assets(source, task_dir / "hidden")
            source_dict = {"task_dir": source.task_dir, "spec": dict(source.spec)}
            source_dict = _ensure_contract_header(source_dict, task_dir)
            source_spec = source_dict["spec"]
            # Carry a generated contract header into the immutable Source view
            # used by task.toml generation.
            if source_spec.get("header_files") != source.spec.get("header_files"):
                source = Source(
                    **{
                        **source.__dict__,
                        "spec": source_spec,
                    }
                )
            baseline, mutation = _baseline(category, source)
            kernel_name = str(source.spec["kernel_file"])
            (task_dir / kernel_name).write_text(baseline, encoding="utf-8")
            (task_dir / "reference" / kernel_name).write_text(
                source.kernel, encoding="utf-8"
            )
            (task_dir / "description.md").write_text(
                _description(category, source, expected), encoding="utf-8"
            )
            difficulty = _difficulty(category, source)
            (task_dir / "task.toml").write_text(
                _task_toml(
                    task_id=task_id,
                    category=category,
                    task_type=task_type,
                    expected=expected,
                    requires_cosim=requires_cosim,
                    difficulty=difficulty,
                    source=source,
                    family=family,
                    hidden_tb=hidden_tb,
                    mutation=mutation,
                ),
                encoding="utf-8",
            )
            manifest_tasks.append(
                {
                    "task_id": task_id,
                    "category": category,
                    "difficulty": difficulty,
                    "source_difficulty": source.source_difficulty,
                    "source_task_id": source.task_id,
                    "source_suite": source.suite,
                    "source_kernel_loc": source.kernel_loc,
                    "source_tb_loc": source.tb_loc,
                    "kernel_family_id": family.family_id,
                    "near_duplicate_cluster_size": len(family.members),
                    "near_duplicate_cluster_members": [
                        member.task_id for member in family.members
                    ],
                    "fault_derivation": mutation,
                    "expected_baseline_state": expected,
                    "requires_cosim": requires_cosim,
                    "previously_completed_in_full199": source.previously_completed,
                    "public_testbench_check_signal": source.public_check_signal,
                    "hidden_testbench_status": hidden_status,
                    "provenance_status": source.provenance["status"],
                    "source_url": source.provenance["source_url"],
                    "reference_normalization": _REFERENCE_NORMALIZATIONS.get(
                        source.task_id, "none"
                    ),
                    "repo_commit": source.provenance["repo_commit"],
                    "license": source.provenance["license"],
                }
            )

    static = _validate_static(output_root)
    if not static["ok"]:
        raise RuntimeError("static corpus validation failed: " + "; ".join(static["errors"]))
    provenance_counts = Counter(item["provenance_status"] for item in manifest_tasks)
    suite_counts = Counter(item["source_suite"] for item in manifest_tasks)
    manifest = {
        "schema_version": 2,
        "purpose": "track_a_150_v2_candidate_corpus",
        "status": "static_input_validated_not_vitis_frozen",
        "task_count": len(manifest_tasks),
        "unique_kernel_family_count": len(
            {item["kernel_family_id"] for item in manifest_tasks}
        ),
        "near_duplicate_policy": {
            "representation": "identifier-and-literal-normalized token 5-gram set",
            "similarity": "Jaccard",
            "threshold": threshold,
            "one_selected_task_per_cluster": True,
        },
        "source_pool": {
            "task_package_count": len(sources),
            "near_duplicate_family_count": len(families),
            "selected_by_suite": dict(sorted(suite_counts.items())),
        },
        "provenance_status_counts": dict(sorted(provenance_counts.items())),
        "static_validation": static,
        "remaining_gates": [
            "replace or verify every UPSTREAM_REVIEW_REQUIRED provenance record",
            "strengthen public/hidden testbenches flagged as weak",
            "fresh Vitis 2025.2 U55C reference and baseline CSim/Synth acceptance",
            "required CoSim acceptance for all structural_cosim_repair tasks",
            "measurable latency/II/resource anchor for all scored tasks",
        ],
        "tasks": sorted(manifest_tasks, key=lambda item: item["task_id"]),
    }
    (output_root / "candidate_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("tasks/generated"))
    parser.add_argument("--output-root", type=Path, default=Path("tasks/track_a_150_v2"))
    parser.add_argument(
        "--prior-report",
        type=Path,
        default=Path(
            "fpt26-agent-v3/scoring/reports/"
            "phase2d_full199_acceptance_with_retry1_20260725.json"
        ),
    )
    parser.add_argument(
        "--near-duplicate-threshold", type=float, default=NEAR_DUPLICATE_THRESHOLD
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build(
        args.source_root,
        args.output_root,
        args.prior_report,
        args.near_duplicate_threshold,
    )
    print(
        json.dumps(
            {
                "output_root": str(args.output_root),
                "task_count": manifest["task_count"],
                "unique_kernel_family_count": manifest[
                    "unique_kernel_family_count"
                ],
                "difficulty_counts": manifest["static_validation"][
                    "difficulty_counts"
                ],
                "weak_public_testbench_count": manifest["static_validation"][
                    "weak_public_testbench_count"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
