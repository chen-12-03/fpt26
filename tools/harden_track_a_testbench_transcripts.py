#!/usr/bin/env python3
"""Stage independent hidden inputs with a self-checking transcript oracle.

This hardener is intended for imported benches that print results but always
return success.  It creates a deterministic hidden input variant, records the
reference stdout/stderr and output files as golden fixtures, and wraps the
hidden bench so any byte-level deviation returns failure.  Output is written
to a staging corpus; source tasks are never modified in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from agent.runner import CSimTool
from agent.testbench import normalize_task_testbench_data
from build_track_a_150 import _inject_early_return
from llm4hls.task import load_task


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _mask_comments(source: str) -> str:
    return re.sub(
        r"//[^\n]*|/\*.*?\*/",
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group(0)),
        source,
        flags=re.S,
    )


def _matching_brace(clean: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(clean)):
        if clean[index] == "{":
            depth += 1
        elif clean[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise RuntimeError("unbalanced braces")


def _function_body(source: str, name: str) -> tuple[int, int]:
    clean = _mask_comments(source)
    match = re.search(rf"\b{re.escape(name)}\s*\(", clean)
    if match is None:
        raise RuntimeError(f"function not found: {name}")
    opening = clean.find("{", match.end())
    if opening < 0:
        raise RuntimeError(f"function body not found: {name}")
    return opening, _matching_brace(clean, opening)


def _replace_terminal_main_return(source: str, status_name: str) -> str:
    """Replace main's final return with a status assignment.

    Generated observation/golden code must run before main exits.  Restrict the
    rewrite to a return that is the last statement in main; inner early exits
    and helper-function returns remain untouched.
    """
    opening, closing = _function_body(source, "main")
    body = source[opening + 1 : closing]
    terminal = re.search(r"\breturn\s+(?P<expr>[^;]+);\s*$", body, re.S)
    if terminal is None:
        replacement = f"\n    int {status_name} = 0;\n"
        return source[:closing] + replacement + source[closing:]
    replacement = f"int {status_name} = ({terminal.group('expr').strip()});\n"
    start = opening + 1 + terminal.start()
    end = opening + 1 + terminal.end()
    return source[:start] + replacement + source[end:]


def _polybench_input_variant(source: str, *, namespace: str) -> tuple[str, str]:
    opening, closing = _function_body(source, "init_array")
    body = source[opening + 1 : closing]
    pattern = re.compile(
        r"(?P<lhs>\b[A-Za-z_]\w*(?:\s*\[[^\]]+\])+\s*)="
        r"(?P<rhs>[^;]+);",
        re.S,
    )
    for match in pattern.finditer(body):
        lhs = match.group("lhs")
        rhs = match.group("rhs").strip()
        indices = []
        for expression in re.findall(r"\[([^\]]+)\]", lhs):
            names = re.findall(r"\b[A-Za-z_]\w*\b", expression)
            if names:
                indices.append(names[0])
        indices = list(dict.fromkeys(indices))
        if not indices or not any(re.search(rf"\b{re.escape(name)}\b", rhs) for name in indices):
            continue
        terms = [f"({name} * {name} + 3 * {name})" for name in indices[:3]]
        if namespace == "public":
            salt, modulus, divisor = 5, 7, 17
        else:
            salt, modulus, divisor = 7, 11, 13
        perturbation = (
            " + (double)(("
            + " + ".join(terms)
            + f" + {salt}) % {modulus}) / {divisor}.0"
        )
        replacement = f"{lhs}= ({rhs}){perturbation};"
        start = opening + 1 + match.start()
        end = opening + 1 + match.end()
        return (
            source[:start] + replacement + source[end:],
            f"polybench_nonlinear_{namespace}_input:{lhs.strip()}:indices={','.join(indices)}",
        )
    raise RuntimeError("no PolyBench init-array assignment candidate")


def _generic_input_variant(
    source: str, top: str, *, namespace: str
) -> tuple[str, str]:
    main_open, main_close = _function_body(source, "main")
    clean = _mask_comments(source)
    calls = [match for match in re.finditer(rf"\b{re.escape(top)}\s*\(", clean)]
    calls = [match for match in calls if main_open < match.start() < main_close]
    if not calls:
        raise RuntimeError("top call not found in main")
    call_match = calls[0]
    call = call_match.start()
    prefix = source[main_open + 1 : call]

    opening = clean.find("(", call_match.start())
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
        raise RuntimeError("unbalanced top call")
    argument_text = clean[opening + 1 : closing]
    arguments = []
    current = []
    depth = 0
    for char in argument_text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            arguments.append("".join(current))
            current = []
        else:
            current.append(char)
    arguments.append("".join(current))
    bases = []
    for argument in arguments:
        identifiers = re.findall(r"\b[A-Za-z_]\w*\b", argument)
        identifiers = [
            name
            for name in identifiers
            if name
            not in {
                "const", "unsigned", "signed", "int", "long", "short",
                "float", "double", "char", "void", "static_cast",
            }
        ]
        if identifiers:
            bases.append(identifiers[0])
    bases = list(dict.fromkeys(bases))
    input_like = re.compile(r"(?:in|input|src|data|key|state|edge|weight|bias|a$|x$|radian)", re.I)
    output_like = re.compile(r"(?:out|output|result|dest|dst|ret)", re.I)
    bases.sort(
        key=lambda name: (
            0 if input_like.search(name) else 2 if output_like.search(name) else 1,
            name,
        )
    )
    base_pattern = "|".join(re.escape(name) for name in bases) or r"(?!)"

    pointer_aliases = list(
        re.finditer(
            rf"\b(?P<name>{base_pattern})\s*=\s*(?P<storage>[A-Za-z_]\w*_storage)\s*;",
            prefix,
        )
    )
    alias_insertions = []
    alias_descriptions = []
    for alias in pointer_aliases:
        name = alias.group("name")
        if output_like.search(name) and not input_like.search(name):
            continue
        storage = alias.group("storage")
        coefficient = 17 if namespace == "public" else 29
        salt = 3 if namespace == "public" else 7
        insertion = (
            f"\n    for (std::size_t track_a_i = 0; "
            f"track_a_i < sizeof({storage}) / sizeof({storage}[0]); ++track_a_i) {{\n"
            f"        {storage}[track_a_i] = track_a_i * {coefficient} + {salt};\n"
            "    }"
        )
        alias_insertions.append((main_open + 1 + alias.end(), insertion))
        alias_descriptions.append(storage)
    if alias_insertions:
        mutated = source
        for end, insertion in reversed(alias_insertions):
            mutated = mutated[:end] + insertion + mutated[end:]
        return (
            mutated,
            f"{namespace}_storage_vectors:{','.join(alias_descriptions)}:"
            f"mul={coefficient}:add={salt}",
        )

    # Prefer explicit aggregate vectors (keys, states, input arrays).  The
    # reference-generated golden is recomputed after this mutation.
    aggregates = list(
        re.finditer(
            rf"\b(?P<name>{base_pattern})\b[^;=]*=\s*\{{(?P<body>.*?)\}}\s*;",
            prefix,
            flags=re.S | re.I,
        )
    )
    for aggregate in aggregates:
        literal = re.search(r"0[xX][0-9A-Fa-f]+|\b\d+\b", aggregate.group("body"))
        if literal is None:
            continue
        start = main_open + 1 + aggregate.start("body") + literal.start()
        end = main_open + 1 + aggregate.start("body") + literal.end()
        old = source[start:end]
        value = int(old, 0)
        mask = 0x33 if namespace == "public" else 0x5A
        increment = 2 if namespace == "public" else 3
        new_value = (value ^ mask) & 0xFF if old.lower().startswith("0x") else value + increment
        replacement = hex(new_value) if old.lower().startswith("0x") else str(new_value)
        return (
            source[:start] + replacement + source[end:],
            f"aggregate_{namespace}_input_literal:{aggregate.group('name')}:{old}->{replacement}",
        )

    assignments = list(
        re.finditer(
            rf"\b(?P<name>{base_pattern})"
            r"(?P<access>(?:(?:\s*\[[^\]]+\])|(?:\s*\.\s*[A-Za-z_]\w*))*)"
            r"\s*=\s*(?P<rhs>[^;]+);",
            prefix,
            flags=re.S | re.I,
        )
    )
    for assignment in assignments:
        # Scalar extent mutations can silently violate interface depth or
        # divisibility preconditions.  Prefer actual data values; if none are
        # available, fail closed and require a manual task-specific variant.
        if re.search(
            r"(?:size|count|length|num(?:ber)?(?:words|items|elements)?)",
            assignment.group("name"),
            re.I,
        ):
            continue
        rhs = assignment.group("rhs")
        literal = re.search(r"0[xX][0-9A-Fa-f]+|\b\d+\b", rhs)
        if literal:
            start = main_open + 1 + assignment.start("rhs") + literal.start()
            end = main_open + 1 + assignment.start("rhs") + literal.end()
            old = source[start:end]
            value = int(old, 0)
            mask = 0x33 if namespace == "public" else 0x5A
            increment = 2 if namespace == "public" else 3
            replacement = hex(value ^ mask) if old.lower().startswith("0x") else str(value + increment)
            return (
                source[:start] + replacement + source[end:],
                f"{namespace}_input_assignment_literal:{assignment.group('name')}:{old}->{replacement}",
            )
        start = main_open + 1 + assignment.start("rhs")
        end = main_open + 1 + assignment.end("rhs")
        return (
            source[:start]
            + f"({rhs.strip()}) + {'2' if namespace == 'public' else '3'}"
            + source[end:],
            f"{namespace}_input_assignment_offset:{assignment.group('name')}",
        )
    raise RuntimeError("no generic input assignment candidate")


_OBSERVATION_HELPERS = r'''
#include <cstddef>
#include <cstdint>
#include <cstdio>

static unsigned long long track_a_hash_bytes(const void *address, std::size_t size) {
    const unsigned char *bytes = static_cast<const unsigned char *>(address);
    unsigned long long value = 1469598103934665603ULL;
    for (std::size_t index = 0; index < size; ++index) {
        value ^= bytes[index];
        value *= 1099511628211ULL;
    }
    return value;
}
'''


def _add_observation_footer(source: str) -> tuple[str, list[str]]:
    main_open, main_close = _function_body(source, "main")
    body = source[main_open + 1 : main_close]
    array_pattern = re.compile(
        r"(?P<prefix>(?:^|[;{}])\s*(?:const\s+)?[A-Za-z_:][\w:<>, ]*\s+)"
        r"(?P<name>[A-Za-z_]\w*)\s*(?P<dims>(?:\[[^\]]+\])+)(?P<init>\s*=\s*[^;]+)?;",
        re.M | re.S,
    )
    arrays = []
    replacements = []
    for match in array_pattern.finditer(body):
        name = match.group("name")
        if name in arrays:
            continue
        arrays.append(name)
        if match.group("init") is None:
            replacements.append((match.end() - 1, match.end() - 1, " = {}"))
    for start, end, replacement in reversed(replacements):
        body = body[:start] + replacement + body[end:]
    source = source[: main_open + 1] + body + source[main_close:]
    _, main_close = _function_body(source, "main")
    source = _replace_terminal_main_return(source, "track_a_pre_observation_status")
    _, main_close = _function_body(source, "main")
    before_close = source[:main_close]
    footer = ["    std::fprintf(stderr, \"\\nTRACK_A_OBSERVATION_BEGIN\\n\");"]
    for name in arrays:
        footer.append(
            f'    std::fprintf(stderr, "{name}=%016llx\\n", '
            f'track_a_hash_bytes(&{name}, sizeof({name})));'
        )
    footer.append('    std::fprintf(stderr, "TRACK_A_OBSERVATION_END\\n");')
    footer.append("    return track_a_pre_observation_status;")
    source = (
        _OBSERVATION_HELPERS
        + "\n"
        + before_close
        + "\n"
        + "\n".join(footer)
        + "\n"
        + source[main_close:]
    )
    return source, arrays


def _input_variant(
    source: str, top: str, task_id: str, *, namespace: str
) -> tuple[str, str]:
    if "__polybench__" in task_id:
        return _polybench_input_variant(source, namespace=namespace)
    return _generic_input_variant(source, top, namespace=namespace)


def _runtime_capture(build_dir: Path, fixture_names: set[str]) -> dict[str, Any]:
    executables = sorted(build_dir.glob("**/csim.exe"))
    if len(executables) != 1:
        raise RuntimeError(f"expected one csim.exe, found {len(executables)}")
    executable = executables[0].resolve()
    completed = subprocess.run(
        [str(executable)],
        cwd=executable.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    outputs: dict[str, bytes] = {}
    for path in sorted(executable.parent.iterdir()):
        if not path.is_file() or path.name in fixture_names:
            continue
        if re.match(r"(?i)^(?:output|out|result)", path.name) and path.suffix.lower() != ".log":
            outputs[path.name] = path.read_bytes()
    return {
        "return_code": completed.returncode,
        "stdout": completed.stdout.replace(b"\r\n", b"\n").replace(b"\r", b"\n"),
        "stderr": completed.stderr.replace(b"\r\n", b"\n").replace(b"\r", b"\n"),
        "outputs": outputs,
    }


_WRAPPER_HELPERS = r'''
#include <cstdio>

static int track_a_compare_file(const char *actual_name, const char *golden_name) {
    FILE *actual = std::fopen(actual_name, "rb");
    FILE *golden = std::fopen(golden_name, "rb");
    if (!actual || !golden) {
        if (actual) std::fclose(actual);
        if (golden) std::fclose(golden);
        return 1;
    }
    int different = 0;
    for (;;) {
        int left = std::fgetc(actual);
        int right = std::fgetc(golden);
        if (left != right) different = 1;
        if (left == EOF || right == EOF) {
            if (left != right) different = 1;
            break;
        }
    }
    std::fclose(actual);
    std::fclose(golden);
    return different;
}
'''


def _wrap_with_golden_checks(
    source: str, output_names: list[str], *, namespace: str
) -> str:
    main_open, main_close = _function_body(source, "main")
    start = (
        f'\n    if (!std::freopen("track_a_{namespace}_stdout.actual", "wb", stdout)) return 97;\n'
        f'    if (!std::freopen("track_a_{namespace}_stderr.actual", "wb", stderr)) return 98;\n'
    )
    source = source[: main_open + 1] + start + source[main_open + 1 :]
    source = _replace_terminal_main_return(source, "track_a_pre_golden_status")
    # Recompute after inserting at the main opening and replacing its return.
    _, main_close = _function_body(source, "main")
    finish_lines = [
        "    std::fflush(stdout);",
        "    std::fflush(stderr);",
        "    std::fclose(stdout);",
        "    std::fclose(stderr);",
        "    int track_a_mismatch = 0;",
        f'    track_a_mismatch |= track_a_compare_file("track_a_{namespace}_stdout.actual", "track_a_{namespace}_stdout.golden");',
        f'    track_a_mismatch |= track_a_compare_file("track_a_{namespace}_stderr.actual", "track_a_{namespace}_stderr.golden");',
    ]
    for index, name in enumerate(output_names):
        finish_lines.append(
            f'    track_a_mismatch |= track_a_compare_file("{name}", "track_a_{namespace}_output_{index}.golden");'
        )
    finish_lines.append(
        "    return (track_a_pre_golden_status != 0 || track_a_mismatch != 0) ? 1 : 0;"
    )
    body = source[:main_close]
    return _WRAPPER_HELPERS + "\n" + body + "\n" + "\n".join(finish_lines) + "\n" + source[main_close:]


def _run(
    task: Any,
    source: str,
    build_dir: Path,
    workspace_root: Path,
    *,
    use_hidden: bool,
) -> tuple[bool, Any]:
    tb_code = task.hidden_tb_code if use_hidden else task.public_tb_code
    tb_name = task.hidden_tb_name if use_hidden else task.public_tb_name
    data_files = (
        getattr(task, "hidden_data_files", None)
        if use_hidden
        else getattr(task, "public_data_files", None)
    ) or None
    files = task.assemble(source, tb_code, tb_name)
    result = CSimTool(workspace_root=workspace_root).run(
        build_dir,
        files,
        top=task.top,
        part=task.part,
        clock_ns=task.clock_ns,
        data_files=data_files,
    )
    return bool(result.ok), result


def harden_one(
    source_dir: Path,
    staging_root: Path,
    evidence_root: Path,
    *,
    preserve_public: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    staged = staging_root / source_dir.name
    checkpoint = evidence_root / source_dir.name / "hardening_evidence.json"
    if checkpoint.is_file() and staged.is_dir():
        existing = json.loads(checkpoint.read_text(encoding="utf-8"))
        if existing.get("schema_version") == 1:
            return existing
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(source_dir, staged)
    task = load_task(staged)
    normalize_task_testbench_data(task, include_hidden=False)
    original_public = task.public_tb_code
    if preserve_public:
        public_input_derivation = "preserved_existing_public_testbench"
        public_observation_arrays = []
    else:
        public_variant, public_input_derivation = _input_variant(
            original_public, task.top, task.id, namespace="public"
        )
        public_variant, public_observation_arrays = _add_observation_footer(public_variant)
        (staged / task.public_tb_name).write_text(public_variant, encoding="utf-8")
        task = load_task(staged)
        normalize_task_testbench_data(task, include_hidden=False)
        public_generation_dir = evidence_root / task.id / "public_golden_generation"
        public_generation_ok, _ = _run(
            task,
            task.reference_code,
            public_generation_dir,
            evidence_root.resolve(),
            use_hidden=False,
        )
        if not public_generation_ok:
            raise RuntimeError(f"{task.id}: reference rejected public input variant")
        public_capture = _runtime_capture(
            public_generation_dir, set((getattr(task, "public_data_files", None) or {}).keys())
        )
        if public_capture["return_code"] != 0:
            raise RuntimeError(f"{task.id}: public reference replay failed")
        if not (
            public_capture["stdout"]
            or public_capture["stderr"]
            or public_capture["outputs"]
        ):
            raise RuntimeError(f"{task.id}: no observable public transcript/output")
        (staged / "track_a_public_stdout.golden").write_bytes(public_capture["stdout"])
        (staged / "track_a_public_stderr.golden").write_bytes(public_capture["stderr"])
        public_output_names = sorted(public_capture["outputs"])
        for index, name in enumerate(public_output_names):
            (staged / f"track_a_public_output_{index}.golden").write_bytes(
                public_capture["outputs"][name]
            )
        (staged / task.public_tb_name).write_text(
            _wrap_with_golden_checks(
                public_variant, public_output_names, namespace="public"
            ),
            encoding="utf-8",
        )

    task = load_task(staged)
    normalize_task_testbench_data(task, include_hidden=True)
    variant, input_derivation = _input_variant(
        task.hidden_tb_code, task.top, task.id, namespace="hidden"
    )
    variant, hidden_observation_arrays = _add_observation_footer(variant)
    hidden_path = staged / "hidden" / task.hidden_tb_name
    hidden_path.write_text(variant, encoding="utf-8")

    task = load_task(staged)
    normalize_task_testbench_data(task, include_hidden=True)
    generation_dir = evidence_root / task.id / "golden_generation"
    reference_ok, _ = _run(
        task,
        task.reference_code,
        generation_dir,
        evidence_root.resolve(),
        use_hidden=True,
    )
    if not reference_ok:
        raise RuntimeError(f"{task.id}: reference rejected input variant")
    capture = _runtime_capture(
        generation_dir, set((getattr(task, "hidden_data_files", None) or {}).keys())
    )
    if capture["return_code"] != 0:
        raise RuntimeError(f"{task.id}: reference replay failed")
    if not (capture["stdout"] or capture["stderr"] or capture["outputs"]):
        raise RuntimeError(f"{task.id}: no observable transcript/output")

    (staged / "hidden" / "track_a_hidden_stdout.golden").write_bytes(capture["stdout"])
    (staged / "hidden" / "track_a_hidden_stderr.golden").write_bytes(capture["stderr"])
    output_names = sorted(capture["outputs"])
    for index, name in enumerate(output_names):
        (staged / "hidden" / f"track_a_hidden_output_{index}.golden").write_bytes(
            capture["outputs"][name]
        )
    hidden_path.write_text(
        _wrap_with_golden_checks(variant, output_names, namespace="hidden"),
        encoding="utf-8",
    )

    task = load_task(staged)
    normalize_task_testbench_data(task, include_hidden=True)
    reference_check, reference_result = _run(
        task,
        task.reference_code,
        evidence_root / task.id / "reference_hardened_hidden",
        evidence_root.resolve(),
        use_hidden=True,
    )
    early_return, mutation = _inject_early_return(task.reference_code, task.top, 173)
    mutant_check, mutant_result = _run(
        task,
        early_return,
        evidence_root / task.id / "early_return_hardened_hidden",
        evidence_root.resolve(),
        use_hidden=True,
    )
    public_reference_check, _ = _run(
        task,
        task.reference_code,
        evidence_root / task.id / "reference_hardened_public",
        evidence_root.resolve(),
        use_hidden=False,
    )
    public_mutant_check, _ = _run(
        task,
        early_return,
        evidence_root / task.id / "early_return_hardened_public",
        evidence_root.resolve(),
        use_hidden=False,
    )
    record = {
        "schema_version": 1,
        "purpose": "track_a_hidden_transcript_hardening_pilot",
        "task_id": task.id,
        "input_derivation": input_derivation,
        "public_input_derivation": public_input_derivation,
        "public_observation_arrays": public_observation_arrays,
        "hidden_observation_arrays": hidden_observation_arrays,
        "oracle_strategy": "reference_generated_transcript_and_output_golden",
        "public_testbench_preserved": preserve_public,
        "reference_hidden_pass": reference_check,
        "reference_public_pass": public_reference_check,
        "early_return_mutation": mutation,
        "early_return_rejected": not mutant_check,
        "public_early_return_rejected": not public_mutant_check,
        "observable_stdout_bytes": len(capture["stdout"]),
        "observable_stderr_bytes": len(capture["stderr"]),
        "observable_output_files": output_names,
        "public_hidden_byte_distinct": (
            (staged / task.public_tb_name).read_bytes() != hidden_path.read_bytes()
        ),
        "staged_task": str(staged),
        "reference_log_tail": str(getattr(reference_result, "log", "") or "")[-4000:],
        "mutant_log_tail": str(getattr(mutant_result, "log", "") or "")[-4000:],
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    _atomic_json(checkpoint, record)
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, default=Path("tasks/track_a_150_v2"))
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument(
        "--audit-json",
        type=Path,
        help="Select every weak_public_task_id from a static audit JSON.",
    )
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument(
        "--preserve-public",
        action="store_true",
        help="Keep an existing self-checking public bench unchanged and harden hidden only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task_ids = list(args.task_id)
    if args.audit_json:
        audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
        task_ids.extend(audit.get("weak_public_task_ids") or [])
        task_ids.extend(audit.get("public_clone_task_ids") or [])
    task_ids = sorted(set(task_ids))
    if not task_ids:
        raise SystemExit("select tasks with --task-id or --audit-json")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("invalid shard index/count")
    task_ids = [
        task_id
        for index, task_id in enumerate(task_ids)
        if index % args.shard_count == args.shard_index
    ]
    selected = []
    for task_id in task_ids:
        task_dir = args.task_root / task_id
        if not (task_dir / "task.toml").is_file():
            raise SystemExit(f"unknown task: {task_id}")
        selected.append(task_dir)
    records = []
    failures = []
    for path in selected:
        try:
            records.append(
                harden_one(
                    path,
                    args.staging_root,
                    args.evidence_root,
                    preserve_public=args.preserve_public,
                )
            )
        except Exception as exc:
            failures.append({"task_id": path.name, "error": f"{type(exc).__name__}: {exc}"})
    summary = {
        "schema_version": 1,
        "purpose": "track_a_hidden_transcript_hardening_summary",
        "task_count": len(records),
        "selected_task_count": len(selected),
        "failure_count": len(failures),
        "failures": failures,
        "reference_hidden_pass_count": sum(item["reference_hidden_pass"] for item in records),
        "reference_public_pass_count": sum(item["reference_public_pass"] for item in records),
        "early_return_rejected_count": sum(item["early_return_rejected"] for item in records),
        "public_early_return_rejected_count": sum(
            item["public_early_return_rejected"] for item in records
        ),
        "public_hidden_distinct_count": sum(item["public_hidden_byte_distinct"] for item in records),
        "tasks": records,
    }
    _atomic_json(
        args.evidence_root / f"hardening_summary_shard_{args.shard_index:02d}.json",
        summary,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not failures and all(
        item["reference_hidden_pass"]
        and item["reference_public_pass"]
        and item["early_return_rejected"]
        and item["public_early_return_rejected"]
        and item["public_hidden_byte_distinct"]
        for item in records
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
