#!/usr/bin/env python3
"""Build the isolated 150-task Track-A corpus from licensed AMD HLS examples.

The builder is deterministic.  It never reads validation/run artifacts and it
never places hidden or reference material in the public task view.  A later
Vitis acceptance pass is authoritative; this script only prepares candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 in the frozen Docker image
    import tomli as tomllib


CATEGORIES: tuple[tuple[str, str, str, bool], ...] = (
    ("code_generation", "generate", "compile_fail", False),
    ("compile_repair", "repair", "compile_fail", False),
    ("synthesis_repair", "synth_fix", "synth_fail", False),
    ("functional_repair", "repair", "csim_fail", False),
    ("structural_cosim_repair", "repair", "cosim_fail", True),
    ("qor_optimization", "optimize", "valid_unoptimized", False),
)
TASKS_PER_CATEGORY = 25
PUBLIC_SOURCE_PREFIXES = ("amd_intro__", "amd_accel__")
PERFORMANCE_PRAGMA = re.compile(
    r"^\s*#\s*pragma\s+HLS\s+"
    r"(?:PIPELINE|UNROLL|ARRAY_PARTITION|ARRAY_RESHAPE|DATAFLOW|INLINE|"
    r"BIND_STORAGE|BIND_OP|LATENCY|ALLOCATION|DEPENDENCE)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
INT_LITERAL = re.compile(r"(?<![\w.])([1-9][0-9]{0,5})(?![\w.])")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized_kernel_hash(value: str) -> str:
    no_comments = re.sub(r"//[^\n]*|/\*.*?\*/", "", value, flags=re.DOTALL)
    return sha256_text("".join(no_comments.split()))


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_sources(source_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for manifest in sorted(source_root.glob("*/task.toml")):
        task_dir = manifest.parent
        if not task_dir.name.startswith(PUBLIC_SOURCE_PREFIXES):
            continue
        raw_spec = tomllib.loads(manifest.read_text(encoding="utf-8"))
        spec = dict(raw_spec)
        spec.update(raw_spec.get("provenance") or {})
        license_id = str(spec.get("license") or "")
        source_url = str(spec.get("source_url") or "")
        repo_commit = str(spec.get("repo_commit") or "")
        if license_id not in {"MIT", "Apache-2.0"}:
            continue
        if not source_url.startswith("https://github.com/") or not repo_commit:
            continue
        kernel_name = str(spec["kernel_file"])
        reference_path = task_dir / "reference" / kernel_name
        reference = (
            reference_path.read_text(encoding="utf-8")
            if reference_path.is_file()
            else (task_dir / kernel_name).read_text(encoding="utf-8")
        )
        kernel_hash = normalized_kernel_hash(reference)
        if kernel_hash in seen_hashes:
            continue
        seen_hashes.add(kernel_hash)
        records.append(
            {
                "task_dir": task_dir,
                "spec": spec,
                "reference": reference,
                "kernel_hash": kernel_hash,
                "pragma_count": len(PERFORMANCE_PRAGMA.findall(reference)),
            }
        )
    if len(records) < len(CATEGORIES) * 16:
        raise RuntimeError(f"not enough unique licensed AMD kernels: {len(records)}")
    return records


def _allocate_families(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Assign each source kernel to exactly one category.

    Seventeen families per category are enough for 25 tasks by making eight
    independent fault variants inside that category.  QoR receives the sources
    with the most removable performance pragmas.
    """

    qor = sorted(records, key=lambda item: (-item["pragma_count"], item["task_dir"].name))[:17]
    used = {item["kernel_hash"] for item in qor}
    remaining = [item for item in records if item["kernel_hash"] not in used]
    allocation: dict[str, list[dict[str, Any]]] = {"qor_optimization": qor}
    code_generation = [
        item for item in remaining if item["spec"].get("header_files")
    ][:17]
    if len(code_generation) != 17:
        raise RuntimeError("not enough header-backed code-generation sources")
    allocation["code_generation"] = code_generation
    used.update(item["kernel_hash"] for item in code_generation)
    remaining = [item for item in remaining if item["kernel_hash"] not in used]
    for category, *_ in CATEGORIES:
        if category in {"qor_optimization", "code_generation"}:
            continue
        allocation[category] = remaining[:17]
        remaining = remaining[17:]
    all_assignments = [item for values in allocation.values() for item in values]
    if len({item["kernel_hash"] for item in all_assignments}) != len(all_assignments):
        raise RuntimeError("source kernel assigned across categories")
    return allocation


def _code_generation_stub(reference: str, top: str) -> str:
    """Keep includes and the exact top declaration, including C/C++ linkage."""

    clean = re.sub(r"//[^\n]*|/\*.*?\*/", " ", reference, flags=re.DOTALL)
    match = re.search(rf"\b{re.escape(top)}\s*\(", clean)
    if match is None:
        raise RuntimeError(f"cannot locate top signature: {top}")
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
    start = match.start()
    while start > 0 and clean[start - 1] not in ";{}":
        start -= 1
    signature = clean[start : close_paren + 1].strip()
    if not re.match(r'^extern\s*"[^"]+"\s+', signature):
        linkage = _enclosing_language_linkage(clean, match.start())
        if linkage is not None:
            signature = f'extern "{linkage}" {signature}'
    includes = "\n".join(
        line for line in reference.splitlines() if line.lstrip().startswith("#include")
    )
    return (
        includes
        + "\n\n"
        + signature
        + " {\n"
        + "#error TRACK_A_CODE_GENERATION_REQUIRED\n"
        + "}\n"
    )


def _enclosing_language_linkage(source: str, position: int) -> str | None:
    """Return the innermost ``extern "..." {}`` linkage enclosing *position*."""

    enclosing: list[tuple[int, str]] = []
    for match in re.finditer(r'\bextern\s*"([^"]+)"\s*\{', source):
        opening = source.find("{", match.start(), match.end())
        depth = 0
        closing = None
        for index in range(opening, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is not None and opening < position < closing:
            enclosing.append((opening, match.group(1)))
    return max(enclosing, default=(0, None), key=lambda item: item[0])[1]


def _inject_early_return(source: str, top: str, variant: int) -> tuple[str, str]:
    """Inject a synthesizable, interface-preserving functional fault."""

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
    return_statement = "return;" if re.search(r"\bvoid\s*$", prefix) else "return {};"
    injection = (
        f"\n  // TRACK_A_INTENTIONAL_EARLY_RETURN_VARIANT_{variant}\n"
        f"  {return_statement}\n"
    )
    return (
        source[: body + 1] + injection + source[body + 1 :],
        f"top_early_return:{return_statement}:variant={variant}",
    )


def _mutate_literal(source: str, variant: int) -> tuple[str, str]:
    """Apply one deterministic semantic fault outside preprocessor lines."""

    candidates = []
    for match in INT_LITERAL.finditer(source):
        line_start = source.rfind("\n", 0, match.start()) + 1
        line = source[line_start : source.find("\n", match.end())]
        if line.lstrip().startswith("#"):
            continue
        if any(token in line for token in ("ap_int<", "ap_uint<", "int", "float", "double")):
            # Type widths and declarations are less likely to create a clean
            # functional/CoSim-only fault than loop bounds or arithmetic.
            continue
        candidates.append(match)
    if not candidates:
        candidates = [
            match
            for match in INT_LITERAL.finditer(source)
            if not source[source.rfind("\n", 0, match.start()) + 1 : match.start()]
            .lstrip()
            .startswith("#")
        ]
    if not candidates:
        operator_patterns = (
            (re.compile(r"\+="), "-="),
            (re.compile(r"-="), "+="),
            (re.compile(r"(?<=\w)\s*\+\s*(?=\w)"), " - "),
            (re.compile(r"(?<=\w)\s*-\s*(?=\w)"), " + "),
            (re.compile(r"\^="), "|="),
        )
        for pattern, replacement in operator_patterns:
            matches = [
                match
                for match in pattern.finditer(source)
                if not source[
                    source.rfind("\n", 0, match.start()) + 1 : match.start()
                ]
                .lstrip()
                .startswith("#")
            ]
            if matches:
                match = matches[variant % len(matches)]
                old = match.group(0)
                mutated = source[: match.start()] + replacement + source[match.end() :]
                return mutated, f"operator:{old.strip()}->{replacement.strip()}:offset={match.start()}"
        raise RuntimeError("no semantic mutation site available")
    match = candidates[variant % len(candidates)]
    old = int(match.group(1))
    new = old + 1 + (variant // max(1, len(candidates)))
    mutated = source[: match.start(1)] + str(new) + source[match.end(1) :]
    return mutated, f"integer_literal:{old}->{new}:offset={match.start(1)}"


def _baseline(
    category: str, reference: str, variant: int, *, top: str
) -> tuple[str, str]:
    if category == "code_generation":
        return (
            _code_generation_stub(reference, top),
            "signature_only_generation_stub",
        )
    if category == "compile_repair":
        return (
            "#error TRACK_A_INTENTIONAL_COMPILE_FAILURE\n" + reference,
            "preprocessor_compile_error",
        )
    if category == "synthesis_repair":
        return (
            "#ifdef __SYNTHESIS__\n"
            "#error TRACK_A_INTENTIONAL_SYNTHESIS_FAILURE\n"
            "#endif\n" + reference,
            "synthesis_only_preprocessor_error",
        )
    if category == "functional_repair":
        return _inject_early_return(reference, top, variant)
    if category == "structural_cosim_repair":
        mutated, mutation = _inject_early_return(reference, top, variant)
        return (
            "#ifndef __SYNTHESIS__\n"
            + reference
            + "\n#else\n"
            + mutated
            + "\n#endif\n",
            "synthesis_only_" + mutation,
        )
    if category == "qor_optimization":
        lines = reference.splitlines()
        pragma_indexes = [
            index
            for index, line in enumerate(lines)
            if PERFORMANCE_PRAGMA.fullmatch(line)
        ]
        if not pragma_indexes:
            raise RuntimeError("QoR source has no removable performance pragma")
        if variant % 3 == 0:
            remove = set(pragma_indexes)
        elif variant % 3 == 1:
            remove = set(pragma_indexes[::2])
        else:
            remove = set(pragma_indexes[1::2] or pragma_indexes[:1])
        baseline = "\n".join(
            line for index, line in enumerate(lines) if index not in remove
        ) + "\n"
        return baseline, f"removed_performance_pragmas:{len(remove)}"
    raise AssertionError(category)


def _copy_public_assets(source: dict[str, Any], destination: Path) -> None:
    source_dir: Path = source["task_dir"]
    spec: dict[str, Any] = source["spec"]
    names = set(spec.get("header_files", []))
    names.add(str(spec["public_tb"]))
    # Testbenches may depend on local fixture files.  Copy non-kernel regular
    # files except old manifests/descriptions and private directories.
    for path in source_dir.iterdir():
        if path.is_dir() or path.name in {
            "task.toml",
            "description.md",
            str(spec["kernel_file"]),
        }:
            continue
        names.add(path.name)
    for name in sorted(names):
        path = source_dir / name
        if path.is_file():
            shutil.copy2(path, destination / name)


def _copy_hidden_assets(source: dict[str, Any], destination: Path) -> str:
    source_dir: Path = source["task_dir"]
    spec: dict[str, Any] = source["spec"]
    hidden_name = str(spec.get("hidden_tb", spec["public_tb"]))
    source_hidden = source_dir / "hidden"
    if source_hidden.is_dir():
        for path in source_hidden.iterdir():
            if path.is_file():
                shutil.copy2(path, destination / path.name)
    if not (destination / hidden_name).is_file():
        shutil.copy2(source_dir / str(spec["public_tb"]), destination / hidden_name)
    # Mirror data fixtures so evaluator-side CSim has a private fixture set.
    for path in source_dir.iterdir():
        if path.is_file() and path.suffix.lower() in {".data", ".dat", ".txt"}:
            shutil.copy2(path, destination / path.name)
    return hidden_name


def _ensure_contract_header(source: dict[str, Any], task_dir: Path) -> dict[str, Any]:
    """Give self-contained kernels an explicit fixed public header artifact."""

    if source["spec"].get("header_files"):
        return source
    copied = dict(source)
    copied["spec"] = dict(source["spec"])
    header_name = "track_a_contract.h"
    copied["spec"]["header_files"] = [header_name]
    guard = (
        "TRACK_A_CONTRACT_"
        + re.sub(r"[^A-Za-z0-9]", "_", source["task_dir"].name).upper()
    )
    (task_dir / header_name).write_text(
        f"#ifndef {guard}\n"
        f"#define {guard}\n\n"
        f"// Fixed public contract for top-level function: {source['spec']['top']}\n"
        "// The complete typed declaration remains in the public baseline source.\n\n"
        f"#endif  // {guard}\n",
        encoding="utf-8",
    )
    return copied


def _description(
    category: str,
    source: dict[str, Any],
    mutation: str,
    expected: str,
) -> str:
    spec = source["spec"]
    original = (source["task_dir"] / "description.md").read_text(
        encoding="utf-8", errors="replace"
    )
    instructions = {
        "code_generation": "Implement the complete HLS kernel from the specification.",
        "compile_repair": "Repair the C/C++ compilation failure without changing the interface.",
        "synthesis_repair": "Repair the HLS synthesis failure while preserving functional behavior.",
        "functional_repair": "Repair the functional defect so all public and hidden tests pass.",
        "structural_cosim_repair": "Repair the RTL/CoSim structural behavior while preserving the public C model.",
        "qor_optimization": "Optimize latency/throughput and area while preserving exact functionality.",
    }[category]
    return (
        f"# Track-A task: {category}\n\n"
        f"{instructions}\n\n"
        "The top-level function, file names, headers, data types, and interfaces are fixed. "
        "Only the kernel source may be changed. Target Alveo U55C, Vitis 2025.2, and at "
        "least 100 MHz. Hidden tests and the reference implementation are evaluator-only.\n\n"
        f"- Expected initial state: `{expected}`\n"
        f"- Fault/derivation record: `{mutation}`\n"
        f"- Upstream source: {spec['source_url']}\n"
        f"- Upstream commit: `{spec['repo_commit']}`\n"
        f"- License: `{spec['license']}`\n\n"
        "## Kernel specification\n\n"
        + original
    )


def _task_toml(
    *,
    task_id: str,
    category: str,
    task_type: str,
    expected: str,
    requires_cosim: bool,
    source: dict[str, Any],
    hidden_tb: str,
    mutation: str,
) -> str:
    spec = source["spec"]
    headers = ", ".join(_quoted(str(item)) for item in spec.get("header_files", []))
    return (
        f"task_id = {_quoted(task_id)}\n"
        f"task_type = {_quoted(task_type)}\n"
        f"track_a_category = {_quoted(category)}\n"
        f"difficulty = {int(spec.get('difficulty', 3))}\n"
        f"top = {_quoted(str(spec['top']))}\n"
        f"kernel_file = {_quoted(str(spec['kernel_file']))}\n"
        f"header_files = [{headers}]\n"
        f"public_tb = {_quoted(str(spec['public_tb']))}\n"
        f"hidden_tb = {_quoted(hidden_tb)}\n"
        "budget = 60\n"
        f"requires_cosim = {'true' if requires_cosim else 'false'}\n"
        f"initial_condition = {_quoted('Track-A ' + category + '; baseline=' + expected)}\n"
        f"expected_baseline_state = {_quoted(expected)}\n"
        f"fault_derivation = {_quoted(mutation)}\n"
        f"kernel_family_id = {_quoted(source['kernel_hash'])}\n"
        f"source_task_id = {_quoted(source['task_dir'].name)}\n"
        f"source_url = {_quoted(str(spec['source_url']))}\n"
        f"source_path = {_quoted(str(spec.get('source_path', '')))}\n"
        f"repo_commit = {_quoted(str(spec['repo_commit']))}\n"
        f"license = {_quoted(str(spec['license']))}\n"
        f"source_sha256 = {_quoted(sha256_text(source['reference']))}\n\n"
        "[target]\n"
        'part = "xcu55c-fsvh2892-2L-e"\n'
        f"clock_ns = {float((spec.get('target') or {}).get('clock_ns', 5.0)):.3f}\n"
        "minimum_frequency_mhz = 100.0\n"
    )


def build(source_root: Path, output_root: Path) -> dict[str, Any]:
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty corpus: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    sources = _load_sources(source_root)
    allocation = _allocate_families(sources)
    manifest_tasks: list[dict[str, Any]] = []

    for category, task_type, expected, requires_cosim in CATEGORIES:
        families = allocation[category]
        for index in range(TASKS_PER_CATEGORY):
            source = families[index % len(families)]
            variant = index // len(families)
            task_id = f"{category}__{index + 1:02d}__{source['task_dir'].name}"
            task_dir = output_root / task_id
            (task_dir / "hidden").mkdir(parents=True)
            (task_dir / "reference").mkdir()
            _copy_public_assets(source, task_dir)
            hidden_tb = _copy_hidden_assets(source, task_dir / "hidden")
            source = _ensure_contract_header(source, task_dir)
            spec = source["spec"]
            baseline, mutation = _baseline(
                category,
                source["reference"],
                variant,
                top=str(spec["top"]),
            )
            kernel_name = str(spec["kernel_file"])
            (task_dir / kernel_name).write_text(baseline, encoding="utf-8")
            (task_dir / "reference" / kernel_name).write_text(
                source["reference"], encoding="utf-8"
            )
            (task_dir / "description.md").write_text(
                _description(category, source, mutation, expected), encoding="utf-8"
            )
            (task_dir / "task.toml").write_text(
                _task_toml(
                    task_id=task_id,
                    category=category,
                    task_type=task_type,
                    expected=expected,
                    requires_cosim=requires_cosim,
                    source=source,
                    hidden_tb=hidden_tb,
                    mutation=mutation,
                ),
                encoding="utf-8",
            )
            manifest_tasks.append(
                {
                    "task_id": task_id,
                    "category": category,
                    "source_task_id": source["task_dir"].name,
                    "kernel_family_id": source["kernel_hash"],
                    "fault_derivation": mutation,
                    "expected_baseline_state": expected,
                    "requires_cosim": requires_cosim,
                    "task_dir": str(task_dir),
                }
            )

    counts = Counter(item["category"] for item in manifest_tasks)
    family_categories: dict[str, set[str]] = defaultdict(set)
    for item in manifest_tasks:
        family_categories[item["kernel_family_id"]].add(item["category"])
    overlap = {
        family: sorted(categories)
        for family, categories in family_categories.items()
        if len(categories) > 1
    }
    if counts != Counter({category: TASKS_PER_CATEGORY for category, *_ in CATEGORIES}):
        raise RuntimeError(f"category count mismatch: {counts}")
    if overlap:
        raise RuntimeError(f"cross-category kernel reuse: {overlap}")

    manifest = {
        "schema_version": 1,
        "purpose": "track_a_150_candidate_corpus",
        "task_count": len(manifest_tasks),
        "category_counts": dict(sorted(counts.items())),
        "unique_kernel_family_count": len(family_categories),
        "cross_category_kernel_overlap_count": 0,
        "source_policy": {
            "allowed_sources": [
                {
                    "repository": "Xilinx/Vitis-HLS-Introductory-Examples",
                    "license": "Apache-2.0",
                },
                {
                    "repository": "Xilinx/Vitis_Accel_Examples",
                    "license": "MIT",
                },
            ],
            "fixed_commit_required": True,
        },
        "tasks": manifest_tasks,
    }
    (output_root / "candidate_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def ensure_headers(source_root: Path, output_root: Path) -> int:
    sources = {item["task_dir"].name: item for item in _load_sources(source_root)}
    changed = 0
    for manifest in sorted(output_root.glob("*/task.toml")):
        current = tomllib.loads(manifest.read_text(encoding="utf-8"))
        if current.get("header_files"):
            continue
        task_dir = manifest.parent
        source = _ensure_contract_header(
            sources[str(current["source_task_id"])], task_dir
        )
        manifest.write_text(
            _task_toml(
                task_id=str(current["task_id"]),
                category=str(current["track_a_category"]),
                task_type=str(current["task_type"]),
                expected=str(current["expected_baseline_state"]),
                requires_cosim=bool(current.get("requires_cosim", False)),
                source=source,
                hidden_tb=str(current["hidden_tb"]),
                mutation=str(current["fault_derivation"]),
            ),
            encoding="utf-8",
        )
        changed += 1
    return changed


def refresh_candidate_manifest(output_root: Path) -> int:
    path = output_root / "candidate_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_id = {str(item["task_id"]): item for item in payload.get("tasks", [])}
    changed = 0
    for manifest in sorted(output_root.glob("*/task.toml")):
        current = tomllib.loads(manifest.read_text(encoding="utf-8"))
        task_id = str(current["task_id"])
        item = by_id.get(task_id)
        if item is None:
            raise RuntimeError(f"task absent from candidate manifest: {task_id}")
        item.update(
            {
                "fault_derivation": current.get("fault_derivation"),
                "expected_baseline_state": current.get("expected_baseline_state"),
                "kernel_family_id": current.get("kernel_family_id"),
                "source_task_id": current.get("source_task_id"),
                "source_url": current.get("source_url"),
                "source_path": current.get("source_path"),
                "repo_commit": current.get("repo_commit"),
                "license": current.get("license"),
                "source_sha256": current.get("source_sha256"),
                "requires_cosim": bool(current.get("requires_cosim", False)),
                "header_files": list(current.get("header_files") or []),
                "task_toml_sha256": sha256_text(manifest.read_text(encoding="utf-8")),
                "baseline_sha256": sha256_text(
                    (manifest.parent / str(current["kernel_file"])).read_text(
                        encoding="utf-8"
                    )
                ),
            }
        )
        changed += 1
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return changed


def refresh_derived(
    source_root: Path, output_root: Path, categories: set[str]
) -> int:
    """Refresh generated baselines/metadata without touching private fixtures."""

    sources = {item["task_dir"].name: item for item in _load_sources(source_root)}
    refreshed = 0
    for manifest in sorted(output_root.glob("*/task.toml")):
        current = tomllib.loads(manifest.read_text(encoding="utf-8"))
        category = str(current["track_a_category"])
        if category not in categories:
            continue
        source = sources[str(current["source_task_id"])]
        task_id = str(current["task_id"])
        index_match = re.match(rf"^{re.escape(category)}__(\d+)__", task_id)
        if index_match is None:
            raise RuntimeError(f"cannot recover variant index: {task_id}")
        variant = (int(index_match.group(1)) - 1) // 17
        source_spec = source["spec"]
        baseline, mutation = _baseline(
            category,
            source["reference"],
            variant,
            top=str(source_spec["top"]),
        )
        task_dir = manifest.parent
        kernel_name = str(source_spec["kernel_file"])
        (task_dir / kernel_name).write_text(baseline, encoding="utf-8")
        expected = str(current["expected_baseline_state"])
        (task_dir / "description.md").write_text(
            _description(category, source, mutation, expected), encoding="utf-8"
        )
        manifest.write_text(
            _task_toml(
                task_id=task_id,
                category=category,
                task_type=str(current["task_type"]),
                expected=expected,
                requires_cosim=bool(current.get("requires_cosim", False)),
                source=source,
                hidden_tb=str(current["hidden_tb"]),
                mutation=mutation,
            ),
            encoding="utf-8",
        )
        refreshed += 1
    candidate_manifest = output_root / "candidate_manifest.json"
    if candidate_manifest.is_file():
        payload = json.loads(candidate_manifest.read_text(encoding="utf-8"))
        by_id = {
            str(item["task_id"]): item for item in payload.get("tasks", [])
        }
        for manifest in sorted(output_root.glob("*/task.toml")):
            current = tomllib.loads(manifest.read_text(encoding="utf-8"))
            task_id = str(current["task_id"])
            if task_id not in by_id:
                continue
            by_id[task_id].update(
                {
                    "fault_derivation": current.get("fault_derivation"),
                    "expected_baseline_state": current.get(
                        "expected_baseline_state"
                    ),
                    "kernel_family_id": current.get("kernel_family_id"),
                }
            )
        candidate_manifest.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return refreshed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path("tasks/generated"))
    parser.add_argument("--output-root", type=Path, default=Path("tasks/track_a_150"))
    parser.add_argument(
        "--refresh-derived",
        action="store_true",
        help="refresh only functional/structural derived baselines in an existing corpus",
    )
    parser.add_argument(
        "--ensure-headers",
        action="store_true",
        help="add a fixed contract header to self-contained task packages",
    )
    parser.add_argument(
        "--refresh-manifest-only",
        action="store_true",
        help="synchronize candidate_manifest.json with current public task files",
    )
    args = parser.parse_args()
    if args.refresh_manifest_only:
        count = refresh_candidate_manifest(args.output_root)
        print(f"manifest_refreshed={count} output={args.output_root}")
        return 0
    if args.ensure_headers:
        count = ensure_headers(args.source_root, args.output_root)
        print(f"headers_added={count} output={args.output_root}")
        return 0
    if args.refresh_derived:
        count = refresh_derived(
            args.source_root,
            args.output_root,
            {"functional_repair", "structural_cosim_repair"},
        )
        print(f"refreshed={count} output={args.output_root}")
        return 0
    manifest = build(args.source_root, args.output_root)
    print(
        f"built={manifest['task_count']} "
        f"unique_families={manifest['unique_kernel_family_count']} "
        f"output={args.output_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
