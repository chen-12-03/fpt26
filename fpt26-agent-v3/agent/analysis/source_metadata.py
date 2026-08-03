"""Deterministic, conservative source metadata for optimization prompts.

This module intentionally implements a small C/C++ recognizer rather than a
compiler.  It reports only syntax that can be identified unambiguously and
uses ``"unknown"`` for everything else.  Parse failures never escape into the
optimization workflow.
"""

from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable


UNKNOWN = "unknown"
DEFAULT_METADATA_PROMPT_CHARS = 700

_ARRAY_DECL_RE = re.compile(
    r"""
    (?P<type>
      \b(?:(?:const|volatile|static|register|unsigned|signed|long|short)\s+)*
      [A-Za-z_]\w*(?:::\w+)*
      (?:\s*<[^;\n{}()]+>)?
      (?:\s*[*&])?
    )
    \s+
    (?P<name>[A-Za-z_]\w*)
    \s*
    (?P<dims>(?:\[\s*[^\]\n]*\s*\]\s*)+)
    """,
    re.VERBOSE,
)
_DIM_RE = re.compile(r"\[\s*([^\]\n]*)\s*\]")
_FOR_RE = re.compile(
    r"(?:(?P<label>\b[A-Za-z_]\w*)\s*:\s*)?"
    r"\bfor\s*\(\s*(?P<init>[^;()]*)\s*;"
    r"\s*(?P<condition>[^;()]*)\s*;"
    r"\s*(?P<increment>[^()]*)\)",
)
_PRAGMA_RE = re.compile(
    r"^[ \t]*\#[ \t]*pragma[ \t]+HLS[ \t]+(?P<body>[^\r\n]+)",
    re.IGNORECASE | re.MULTILINE,
)
_FUNCTION_PARAMS_RE = re.compile(
    r"\b[A-Za-z_]\w*\s*\((?P<params>[^(){};]*)\)\s*(?:const\s*)?\{"
)
_FUNCTION_DEFINITION_RE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:<[^;{}()]*>)?\s*\([^;{}]*\)\s*(?:const\s*)?\{"
)
_POINTER_PARAM_RE = re.compile(
    r"^\s*(?P<type>"
    r"(?:(?:const|volatile|unsigned|signed|long|short)\s+)*"
    r"[A-Za-z_]\w*(?:::\w+)*(?:\s*<[^>]+>)?"
    r")\s*\*+\s*(?P<name>[A-Za-z_]\w*)\s*$"
)
_DEFINE_INT_RE = re.compile(
    r"^[ \t]*#[ \t]*define[ \t]+(?P<name>[A-Za-z_]\w*)"
    r"[ \t]+(?P<value>\d+)[ \t]*$",
    re.MULTILINE,
)
_CONST_INT_RE = re.compile(
    r"\b(?:static\s+)?const\s+(?:unsigned\s+)?(?:int|long|short)"
    r"\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>[A-Za-z_]\w*|\d+)\s*;"
)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        try:
            text = str(value)
        except Exception:
            return ""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _mask_comments_and_strings(source: str) -> str:
    """Replace comments/string bodies with spaces while retaining positions."""
    output = list(source)
    index = 0
    state = "code"
    quote = ""
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if current == "/" and following == "/":
                output[index] = output[index + 1] = " "
                index += 2
                state = "line_comment"
                continue
            if current == "/" and following == "*":
                output[index] = output[index + 1] = " "
                index += 2
                state = "block_comment"
                continue
            if current in {'"', "'"}:
                quote = current
                output[index] = " "
                index += 1
                state = "string"
                continue
        elif state == "line_comment":
            if current == "\n":
                state = "code"
            else:
                output[index] = " "
        elif state == "block_comment":
            if current == "*" and following == "/":
                output[index] = output[index + 1] = " "
                index += 2
                state = "code"
                continue
            if current != "\n":
                output[index] = " "
        elif state == "string":
            if current == "\\" and following:
                output[index] = output[index + 1] = " "
                index += 2
                continue
            if current == quote:
                output[index] = " "
                state = "code"
            elif current != "\n":
                output[index] = " "
        index += 1
    return "".join(output)


def _matching_brace(source: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _int(text: str) -> int | None:
    value = text.strip()
    if re.fullmatch(r"[+-]?\d+", value):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _pragma_value(body: str, key: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(key)}\s*=\s*([A-Za-z_]\w*|[+-]?\d+)",
        body,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _directive_pragmas(source: str) -> list[dict[str, Any]]:
    pragmas: list[dict[str, Any]] = []
    for match in _PRAGMA_RE.finditer(source):
        body = re.sub(r"\s+", " ", match.group("body")).strip()
        directive_match = re.match(r"([A-Za-z_]\w*)", body)
        if not directive_match:
            continue
        pragmas.append(
            {
                "directive": directive_match.group(1).upper(),
                "body": body,
                "text": "#pragma HLS " + body,
                "start": match.start(),
                "end": match.end(),
            }
        )
    return pragmas


def _loop_header(
    init: str, condition: str, increment: str
) -> dict[str, Any]:
    init_match = re.match(
        r"\s*(?:(?:const|unsigned|signed|long|short|int|size_t|auto)\s+)*"
        r"(?P<var>[A-Za-z_]\w*)\s*=\s*(?P<start>.+?)\s*$",
        init,
    )
    if not init_match:
        return {
            "induction_variable": UNKNOWN,
            "lower_bound": UNKNOWN,
            "upper_bound": UNKNOWN,
            "step": UNKNOWN,
            "trip_count": UNKNOWN,
        }
    variable = init_match.group("var")
    start_text = init_match.group("start").strip()
    condition_match = re.match(
        rf"\s*{re.escape(variable)}\s*(<=|<|>=|>)\s*(.+?)\s*$",
        condition,
    )
    upper_text = condition_match.group(2).strip() if condition_match else UNKNOWN
    operator = condition_match.group(1) if condition_match else ""

    step_value: int | None = None
    compact_increment = re.sub(r"\s+", "", increment)
    if compact_increment in {f"++{variable}", f"{variable}++"}:
        step_value = 1
    elif compact_increment in {f"--{variable}", f"{variable}--"}:
        step_value = -1
    else:
        step_match = re.fullmatch(
            rf"{re.escape(variable)}([+-])=(-?\d+)", compact_increment
        )
        if step_match:
            magnitude = int(step_match.group(2))
            step_value = magnitude if step_match.group(1) == "+" else -magnitude

    trip_count: int | str = UNKNOWN
    start_value = _int(start_text)
    upper_value = _int(upper_text)
    if (
        start_value is not None
        and upper_value is not None
        and step_value not in {None, 0}
    ):
        if operator == "<" and step_value > 0:
            trip_count = max(0, math.ceil((upper_value - start_value) / step_value))
        elif operator == "<=" and step_value > 0:
            trip_count = max(
                0, math.floor((upper_value - start_value) / step_value) + 1
            )
        elif operator == ">" and step_value < 0:
            trip_count = max(
                0, math.ceil((start_value - upper_value) / abs(step_value))
            )
        elif operator == ">=" and step_value < 0:
            trip_count = max(
                0,
                math.floor((start_value - upper_value) / abs(step_value)) + 1,
            )

    return {
        "induction_variable": variable,
        "lower_bound": start_text or UNKNOWN,
        "upper_bound": upper_text or UNKNOWN,
        "step": str(step_value) if step_value is not None else UNKNOWN,
        "trip_count": trip_count,
    }


def _report_name(
    label: str | None,
    loop_index: int,
    loop_count: int,
    metrics: list[dict[str, Any]],
) -> str:
    names = [str(item.get("name", "")) for item in metrics if item.get("name")]
    if label:
        exact = [name for name in names if name == label]
        if len(exact) == 1:
            return exact[0]
        token_matches = [
            name
            for name in names
            if label in re.findall(r"[A-Za-z_]\w*", name)
        ]
        if len(token_matches) == 1:
            return token_matches[0]
    if loop_count == 1 and len(names) == 1 and loop_index == 0:
        return names[0]
    return UNKNOWN


def _loop_pragmas(
    loop: dict[str, Any],
    loops: list[dict[str, Any]],
    pragmas: list[dict[str, Any]],
    source: str,
) -> list[dict[str, Any]]:
    attached: list[dict[str, Any]] = []
    body_open = loop.get("_body_open")
    body_end = loop.get("_body_end")
    if isinstance(body_open, int) and isinstance(body_end, int):
        for pragma in pragmas:
            if not (body_open < pragma["start"] < body_end):
                continue
            containing = [
                item
                for item in loops
                if isinstance(item.get("_body_open"), int)
                and isinstance(item.get("_body_end"), int)
                and item["_body_open"] < pragma["start"] < item["_body_end"]
            ]
            if containing and max(
                containing, key=lambda item: item["_body_open"]
            ) is not loop:
                continue
            prefix = source[body_open + 1 : pragma["start"]]
            prefix = _PRAGMA_RE.sub("", prefix)
            if not prefix.strip():
                attached.append(pragma)

    return attached


def _parse_loop_directives(pragmas: list[dict[str, Any]]) -> tuple[dict, dict]:
    pipeline: dict[str, Any] = {"enabled": False, "ii": UNKNOWN}
    unroll: dict[str, Any] = {"enabled": False, "factor": UNKNOWN}
    for pragma in pragmas:
        if pragma["directive"] == "PIPELINE":
            raw_ii = _pragma_value(pragma["body"], "ii")
            pipeline = {
                "enabled": True,
                "ii": _int(raw_ii) if raw_ii and _int(raw_ii) is not None else (
                    raw_ii or UNKNOWN
                ),
            }
        elif pragma["directive"] == "UNROLL":
            raw_factor = _pragma_value(pragma["body"], "factor")
            unroll = {
                "enabled": True,
                "factor": (
                    _int(raw_factor)
                    if raw_factor and _int(raw_factor) is not None
                    else (raw_factor or "complete")
                ),
            }
    return pipeline, unroll


def _storage_directive(
    pragmas: Iterable[dict[str, Any]], directive: str, variable: str
) -> dict[str, Any] | str:
    matches = [
        pragma
        for pragma in pragmas
        if pragma["directive"] == directive
        and _pragma_value(pragma["body"], "variable") == variable
    ]
    if not matches:
        return "none"
    body = matches[-1]["body"]
    kind = _pragma_value(body, "type")
    if not kind:
        word = re.search(r"\b(complete|cyclic|block)\b", body, re.IGNORECASE)
        kind = word.group(1) if word else UNKNOWN
    factor = _pragma_value(body, "factor")
    dim = _pragma_value(body, "dim")
    return {
        "type": kind.lower() if kind != UNKNOWN else UNKNOWN,
        "factor": _int(factor) if factor and _int(factor) is not None else (
            factor or UNKNOWN
        ),
        "dim": _int(dim) if dim and _int(dim) is not None else (dim or UNKNOWN),
    }


def _access_pattern(
    source: str,
    name: str,
    declaration_spans: list[tuple[int, int]],
    induction_variables: list[str],
) -> dict[str, Any]:
    accesses: list[str] = []
    pattern = re.compile(rf"\b{re.escape(name)}\s*\[\s*([^\]\n]+)\s*\]")
    for match in pattern.finditer(source):
        if any(start <= match.start() < end for start, end in declaration_spans):
            continue
        accesses.append(re.sub(r"\s+", "", match.group(1)))
    if not accesses:
        return {"kind": UNKNOWN, "stride": UNKNOWN}

    classifications: list[tuple[str, int | str]] = []
    for expression in accesses:
        if _int(expression) is not None:
            classifications.append(("constant_index", UNKNOWN))
            continue
        matched = False
        for variable in induction_variables:
            if re.fullmatch(rf"{re.escape(variable)}(?:[+-]\d+)?", expression):
                classifications.append(("contiguous", 1))
                matched = True
                break
            stride = re.fullmatch(
                rf"(?:{re.escape(variable)}\*(\d+)|(\d+)\*{re.escape(variable)})"
                rf"(?:[+-]\d+)?",
                expression,
            )
            if stride:
                classifications.append(
                    ("fixed_stride", int(stride.group(1) or stride.group(2)))
                )
                matched = True
                break
        if not matched:
            classifications.append((UNKNOWN, UNKNOWN))
    if len(set(classifications)) == 1:
        kind, stride = classifications[0]
        return {"kind": kind, "stride": stride}
    return {"kind": UNKNOWN, "stride": UNKNOWN}


def _array_access_records(
    source: str,
    name: str,
    declaration_spans: list[tuple[int, int]],
    loops: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return bounded, syntax-backed array access records."""
    records: list[dict[str, Any]] = []
    pattern = re.compile(
        rf"\b{re.escape(name)}\s*"
        r"(?P<dims>(?:\[\s*[^\]\n]+\s*\]\s*)+)"
    )
    for match in pattern.finditer(source):
        if any(start <= match.start() < end for start, end in declaration_spans):
            continue
        containing = [
            loop
            for loop in loops
            if isinstance(loop.get("_body_open"), int)
            and isinstance(loop.get("_body_end"), int)
            and loop["_body_open"] < match.start() < loop["_body_end"]
        ]
        innermost = (
            max(containing, key=lambda item: item["_body_open"])
            if containing
            else None
        )
        statement_start = max(
            source.rfind(";", 0, match.start()),
            source.rfind("{", 0, match.start()),
            source.rfind("}", 0, match.start()),
        ) + 1
        statement_end = source.find(";", match.end())
        if statement_end < 0:
            statement_end = len(source)
        statement = source[statement_start:statement_end]
        offset = match.start() - statement_start
        assignment = re.search(r"(?<![=!<>])(?:\+=|-=|\*=|/=|=)(?!=)", statement)
        mode = (
            "write"
            if assignment is not None and offset < assignment.start()
            else "read"
        )
        records.append(
            {
                "dimensions": [
                    re.sub(r"\s+", "", value)
                    for value in _DIM_RE.findall(match.group("dims"))
                ],
                "mode": mode,
                "loop": (
                    str(innermost.get("label") or UNKNOWN)
                    if innermost is not None
                    else UNKNOWN
                ),
                "induction_variable": (
                    str(innermost.get("induction_variable") or UNKNOWN)
                    if innermost is not None
                    else UNKNOWN
                ),
                "nesting_depth": (
                    innermost.get("nesting_depth", UNKNOWN)
                    if innermost is not None
                    else UNKNOWN
                ),
            }
        )
        if len(records) >= 12:
            break
    return records


def _constant_values(source: str) -> dict[str, int]:
    values = {
        match.group("name"): int(match.group("value"))
        for match in _DEFINE_INT_RE.finditer(source)
    }
    pending = list(_CONST_INT_RE.finditer(source))
    for _ in range(len(pending) + 1):
        changed = False
        for match in pending:
            raw = match.group("value")
            value = int(raw) if raw.isdigit() else values.get(raw)
            if value is not None and values.get(match.group("name")) != value:
                values[match.group("name")] = value
                changed = True
        if not changed:
            break
    return values


def _positive_int_expression(
    expression: Any,
    constants: dict[str, int],
) -> int | None:
    """Evaluate a bounded integer extent without executing source code."""
    try:
        parsed = ast.parse(str(expression).strip(), mode="eval")
    except (SyntaxError, ValueError):
        return None

    def evaluate(node: ast.AST) -> int | None:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant):
            return (
                int(node.value)
                if isinstance(node.value, int) and not isinstance(node.value, bool)
                else None
            )
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            return evaluate(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv)
        ):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            else:
                if right == 0:
                    return None
                value = left // right
            return value if 0 < value <= 2**31 - 1 else None
        return None

    result = evaluate(parsed)
    return result if isinstance(result, int) and result > 0 else None


def _pointer_parameters(source: str) -> list[dict[str, Any]]:
    """Return unambiguous pointer declarations from function parameter lists."""
    pointers: list[dict[str, Any]] = []
    for function in _FUNCTION_PARAMS_RE.finditer(source):
        params = function.group("params")
        params_start = function.start("params")
        piece_start = 0
        square_depth = 0
        angle_depth = 0
        pieces: list[tuple[int, int]] = []
        for index, character in enumerate(params):
            if character == "[":
                square_depth += 1
            elif character == "]":
                square_depth = max(0, square_depth - 1)
            elif character == "<":
                angle_depth += 1
            elif character == ">":
                angle_depth = max(0, angle_depth - 1)
            elif character == "," and square_depth == 0 and angle_depth == 0:
                pieces.append((piece_start, index))
                piece_start = index + 1
        pieces.append((piece_start, len(params)))
        for start, end in pieces:
            text = params[start:end]
            match = _POINTER_PARAM_RE.match(text)
            if not match:
                continue
            pointers.append(
                {
                    "name": match.group("name"),
                    "element_type": re.sub(
                        r"\s+", " ", match.group("type")
                    ).strip(),
                    "start": params_start + start,
                    "end": params_start + end,
                }
            )
    return pointers


def source_architecture_evidence(
    source: Any,
    *,
    top_function: str,
) -> list[dict[str, Any]]:
    """Return source-proven task-pipeline opportunities.

    The recognizer is deliberately structural: it does not inspect task IDs,
    descriptions, benchmark names, or reference code.  An opportunity exists
    only when the editable top function calls at least two locally defined
    stages and those calls share a local array/stream connector.  This is the
    minimum source evidence required to make DATAFLOW-style task overlap a
    measurable hypothesis instead of a workload-specific guess.
    """

    text = _safe_text(source)
    top = str(top_function or "").strip()
    if not text.strip() or not re.fullmatch(r"[A-Za-z_]\w*", top):
        return []
    try:
        clean = _mask_comments_and_strings(text)
        definitions: dict[str, tuple[int, int]] = {}
        for match in _FUNCTION_DEFINITION_RE.finditer(clean):
            name = match.group("name")
            if name in {"if", "for", "while", "switch", "catch"}:
                continue
            opening = clean.find("{", match.start(), match.end())
            closing = _matching_brace(clean, opening)
            if opening >= 0 and closing is not None:
                definitions.setdefault(name, (opening, closing))
        if top not in definitions:
            return []

        opening, closing = definitions[top]
        body = clean[opening + 1 : closing]
        helper_names = set(definitions) - {top}
        calls: list[dict[str, Any]] = []
        call_re = re.compile(
            r"\b(?P<name>[A-Za-z_]\w*)\s*"
            r"(?:<[^;{}()]*>)?\s*\((?P<args>[^;{}()]*)\)\s*;"
        )
        for match in call_re.finditer(body):
            name = match.group("name")
            if name not in helper_names:
                continue
            arguments = [
                token
                for token in re.findall(r"\b[A-Za-z_]\w*\b", match.group("args"))
                if token not in {"true", "false", "nullptr"}
            ]
            calls.append({"stage": name, "arguments": arguments})
            if len(calls) >= 16:
                break
        if len(calls) < 2:
            return []

        local_arrays = {
            match.group("name")
            for match in _ARRAY_DECL_RE.finditer(body)
        }
        local_streams = {
            match.group(1)
            for match in re.finditer(
                r"\b(?:hls::)?stream\s*<[^;{}>]+(?:>[^;{}>]*)?>\s*"
                r"(?:\(&?\s*)?([A-Za-z_]\w*)",
                body,
            )
        }
        local_connectors = local_arrays | local_streams
        use_counts: dict[str, int] = {}
        for call in calls:
            for token in set(call["arguments"]):
                if token in local_connectors:
                    use_counts[token] = use_counts.get(token, 0) + 1
        connectors = sorted(
            token for token, count in use_counts.items() if count >= 2
        )
        if not connectors:
            return []

        pragmas = _directive_pragmas(body)
        existing_dataflow = any(
            pragma["directive"] == "DATAFLOW" for pragma in pragmas
        )
        if existing_dataflow:
            return []
        return [
            {
                "kind": "source_connected_task_pipeline",
                "top_function": top,
                "stage_calls": [call["stage"] for call in calls],
                "connectors": connectors[:12],
                "connector_kinds": {
                    connector: (
                        "stream" if connector in local_streams else "local_array"
                    )
                    for connector in connectors[:12]
                },
                "existing_dataflow": False,
                "candidate_families": [
                    "TASK_PIPELINE",
                    "SOURCE_RESTRUCTURE",
                ],
                "candidate_scheme": (
                    "Treat the connected helper calls as stages: preserve the "
                    "top interface and arithmetic, establish explicit stage "
                    "boundaries, and test task overlap as one coherent candidate."
                ),
                "verification": [
                    "C-simulation preserves behavior",
                    "synthesis changes top-level schedule or interval",
                    "capacity-normalized scoring_v3 Q_HW exceeds baseline",
                ],
            }
        ]
    except Exception:
        return []


def source_reduction_parallelism_evidence(
    source: Any,
    *,
    top_function: str,
    constant_context: Any = "",
) -> list[dict[str, Any]]:
    """Return source-proven affine reduction opportunities.

    A finding requires an accumulator update inside a statically bounded loop,
    affine input-array reads indexed by that loop, and at least one named source
    constant that is a valid divisor of the trip count.  The named constants
    become a finite parameter space; this function never invents a factor.
    """

    text = _safe_text(source)
    top = str(top_function or "").strip()
    if not text.strip() or not re.fullmatch(r"[A-Za-z_]\w*", top):
        return []
    try:
        clean = _mask_comments_and_strings(text)
        top_body = ""
        for match in _FUNCTION_DEFINITION_RE.finditer(clean):
            if match.group("name") != top:
                continue
            opening = clean.find("{", match.start(), match.end())
            closing = _matching_brace(clean, opening)
            if opening >= 0 and closing is not None:
                top_body = clean[opening + 1 : closing]
                break
        if not top_body:
            return []

        constants = _constant_values(
            _mask_comments_and_strings(_safe_text(constant_context))
            + "\n"
            + clean
        )
        findings: list[dict[str, Any]] = []
        for loop_index, match in enumerate(_FOR_RE.finditer(top_body)):
            after = match.end()
            while after < len(top_body) and top_body[after].isspace():
                after += 1
            if after >= len(top_body) or top_body[after] != "{":
                continue
            closing = _matching_brace(top_body, after)
            if closing is None:
                continue
            header = _loop_header(
                match.group("init"),
                match.group("condition"),
                match.group("increment"),
            )
            induction = str(header.get("induction_variable") or UNKNOWN)
            if induction == UNKNOWN:
                continue
            trip_count = header.get("trip_count")
            upper = str(header.get("upper_bound") or "")
            if (
                trip_count == UNKNOWN
                and header.get("lower_bound") == "0"
                and header.get("step") == "1"
                and upper in constants
            ):
                trip_count = constants[upper]
            if not isinstance(trip_count, int) or trip_count < 2:
                continue

            loop_body = top_body[after + 1 : closing]
            for reduction in re.finditer(
                r"\b(?P<acc>[A-Za-z_]\w*)\s*\+=\s*"
                r"(?P<rhs>[^;]+);",
                loop_body,
            ):
                rhs = reduction.group("rhs")
                input_arrays = sorted(
                    {
                        array_match.group("name")
                        for array_match in re.finditer(
                            r"\b(?P<name>[A-Za-z_]\w*)\s*\[\s*"
                            r"(?P<index>[^\]\n]+)\s*\]",
                            rhs,
                        )
                        if re.search(
                            rf"(?<![A-Za-z0-9_]){re.escape(induction)}"
                            rf"(?![A-Za-z0-9_])",
                            array_match.group("index"),
                        )
                    }
                )
                if not input_arrays:
                    continue
                factor_candidates = [
                    {"name": name, "value": value}
                    for name, value in sorted(constants.items())
                    if name != upper
                    and re.search(
                        r"(?:^|_)(?:PAR|PARALLEL|FACTOR|LANES?|TILE|BLOCK|UNROLL)(?:_|$)",
                        name,
                        re.IGNORECASE,
                    )
                    and 2 <= value <= trip_count
                    and trip_count % value == 0
                ][:8]
                if not factor_candidates:
                    continue
                findings.append(
                    {
                        "kind": "source_affine_reduction_parallelism",
                        "top_function": top,
                        "loop": match.group("label") or f"loop_{loop_index}",
                        "induction_variable": induction,
                        "trip_count": trip_count,
                        "accumulator": reduction.group("acc"),
                        "input_arrays": input_arrays,
                        "factor_candidates": factor_candidates,
                        "candidate_families": [
                            "REDUCTION_PARALLELISM",
                            "SOURCE_RESTRUCTURE",
                        ],
                        "composite_family": "REDUCTION_PARALLELISM",
                        "composite_family_members": [
                            "SOURCE_RESTRUCTURE",
                            "MEMORY_BANKING",
                            "PIPELINE",
                            "LOOP_UNROLL",
                            "LATENCY",
                        ],
                        "candidate_scheme": (
                            "Tile or lane the proven affine reduction using "
                            "one named factor candidate; bank only the named "
                            "input arrays consistently with that factor and "
                            "preserve the accumulator's numeric semantics."
                        ),
                        "verification": [
                            "C-simulation preserves numeric tolerance",
                            "synthesis measures the chosen factor",
                            "capacity-normalized scoring_v3 Q_HW exceeds baseline",
                        ],
                    }
                )
                if len(findings) >= 4:
                    return findings
        return findings
    except Exception:
        return []


@dataclass(frozen=True)
class DesignMetadata:
    loops: tuple[dict[str, Any], ...]
    arrays: tuple[dict[str, Any], ...]
    constants: tuple[dict[str, Any], ...] = ()
    parse_status: str = "ok"
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "parse_status": self.parse_status,
            "loops": [dict(item) for item in self.loops],
            "arrays": [dict(item) for item in self.arrays],
            "constants": [dict(item) for item in self.constants],
            "truncated": self.truncated,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )


def extract_design_metadata(
    source: Any,
    *,
    loop_metrics: Iterable[dict[str, Any]] | None = None,
    inferred_directives: Iterable[dict[str, Any]] | None = None,
    constant_context: Any = "",
) -> DesignMetadata:
    """Extract stable loop/array metadata; return an empty result on failure."""
    text = _safe_text(source)
    if not text.strip():
        return DesignMetadata((), (), parse_status="empty")
    try:
        clean = _mask_comments_and_strings(text)
        constant_values = _constant_values(
            _mask_comments_and_strings(_safe_text(constant_context))
            + "\n"
            + clean
        )
        pragmas = _directive_pragmas(clean)
        metrics = [dict(item) for item in (loop_metrics or [])]
        inferred = [
            dict(item)
            for item in (inferred_directives or [])
            if isinstance(item, dict)
        ]
        inferred_by_scope: dict[str, set[str]] = {}
        for item in inferred:
            scope = str(item.get("scope") or "").strip()
            kind = str(item.get("kind") or "").strip().lower()
            if scope and kind:
                inferred_by_scope.setdefault(scope, set()).add(kind)

        loop_matches = list(_FOR_RE.finditer(clean))
        internal_loops: list[dict[str, Any]] = []
        for index, match in enumerate(loop_matches):
            after = match.end()
            while after < len(clean) and clean[after].isspace():
                after += 1
            body_open = after if after < len(clean) and clean[after] == "{" else None
            body_end = (
                _matching_brace(clean, body_open)
                if isinstance(body_open, int)
                else None
            )
            nesting_depth = sum(
                1
                for parent in internal_loops
                if isinstance(parent.get("_body_end"), int)
                and parent["_body_open"] < match.start() < parent["_body_end"]
            )
            parents = [
                parent
                for parent in internal_loops
                if isinstance(parent.get("_body_end"), int)
                and parent["_body_open"] < match.start() < parent["_body_end"]
            ]
            header = _loop_header(
                match.group("init"),
                match.group("condition"),
                match.group("increment"),
            )
            if (
                header["trip_count"] == UNKNOWN
                and header["lower_bound"] == "0"
                and header["step"] == "1"
                and header["upper_bound"] in constant_values
            ):
                header["trip_count"] = constant_values[header["upper_bound"]]
            internal_loops.append(
                {
                    "_start": match.start(),
                    "_body_open": body_open,
                    "_body_end": body_end,
                    "_index": index,
                    "_ancestor_labels": [
                        str(parent.get("label") or UNKNOWN)
                        for parent in parents
                        if str(parent.get("label") or UNKNOWN) != UNKNOWN
                    ],
                    "label": match.group("label") or UNKNOWN,
                    "nesting_depth": nesting_depth,
                    **header,
                }
            )

        loops: list[dict[str, Any]] = []
        for internal in internal_loops:
            attached = _loop_pragmas(internal, internal_loops, pragmas, clean)
            pipeline, unroll = _parse_loop_directives(attached)
            label = internal["label"]
            inferred_kinds = sorted(
                inferred_by_scope.get(
                    str(label if label != UNKNOWN else ""), set()
                )
            )
            inferred_pipeline_ancestors = [
                ancestor
                for ancestor in internal["_ancestor_labels"]
                if "pipeline" in inferred_by_scope.get(ancestor, set())
            ]
            loops.append(
                {
                    "name": label if label != UNKNOWN else f"loop_{internal['_index']}",
                    "label": label,
                    "nesting_depth": internal["nesting_depth"],
                    "induction_variable": internal["induction_variable"],
                    "lower_bound": internal["lower_bound"],
                    "upper_bound": internal["upper_bound"],
                    "step": internal["step"],
                    "trip_count": internal["trip_count"],
                    "ancestor_loops": list(internal["_ancestor_labels"]),
                    "pipeline": pipeline,
                    "unroll": unroll,
                    "vitis_inferred_directives": inferred_kinds,
                    "auto_parallelism": {
                        "pipeline": "pipeline" in inferred_kinds,
                        "unroll": "unroll" in inferred_kinds,
                        "flatten": "loop_flatten" in inferred_kinds,
                        "pipeline_ancestors": inferred_pipeline_ancestors,
                        "hierarchy_sensitive": bool(
                            inferred_pipeline_ancestors
                            or "pipeline" in inferred_kinds
                            or "loop_flatten" in inferred_kinds
                            or "unroll" in inferred_kinds
                        ),
                    },
                    "report_loop_name": _report_name(
                        None if label == UNKNOWN else label,
                        internal["_index"],
                        len(internal_loops),
                        metrics,
                    ),
                }
            )

        declarations = list(_ARRAY_DECL_RE.finditer(clean))
        pointer_parameters = _pointer_parameters(clean)
        function_param_spans = [
            (match.start("params"), match.end("params"))
            for match in _FUNCTION_PARAMS_RE.finditer(clean)
        ]
        declaration_spans = [
            (match.start(), match.end()) for match in declarations
        ] + [
            (item["start"], item["end"]) for item in pointer_parameters
        ]
        induction_variables = [
            loop["induction_variable"]
            for loop in loops
            if loop["induction_variable"] != UNKNOWN
        ]
        arrays: list[dict[str, Any]] = []
        seen_arrays: set[str] = set()
        for match in declarations:
            name = match.group("name")
            if name in seen_arrays:
                continue
            seen_arrays.add(name)
            extents = [
                extent.strip() or UNKNOWN
                for extent in _DIM_RE.findall(match.group("dims"))
            ]
            storage = (
                "parameter"
                if any(
                    start <= match.start() < end
                    for start, end in function_param_spans
                )
                else "local"
            )
            arrays.append(
                {
                    "name": name,
                    "element_type": re.sub(
                        r"\s+", " ", match.group("type")
                    ).strip(),
                    "rank": len(extents),
                    "extents": extents,
                    "storage": storage,
                    "partition": _storage_directive(
                        pragmas, "ARRAY_PARTITION", name
                    ),
                    "reshape": _storage_directive(
                        pragmas, "ARRAY_RESHAPE", name
                    ),
                    "access_pattern": _access_pattern(
                        clean,
                        name,
                        declaration_spans,
                        induction_variables,
                    ),
                    "accesses": _array_access_records(
                        clean,
                        name,
                        declaration_spans,
                        internal_loops,
                    ),
                }
            )
        for pointer in pointer_parameters:
            name = pointer["name"]
            if name in seen_arrays:
                continue
            seen_arrays.add(name)
            arrays.append(
                {
                    "name": name,
                    "element_type": pointer["element_type"],
                    "rank": UNKNOWN,
                    "extents": [UNKNOWN],
                    "storage": "parameter",
                    "partition": _storage_directive(
                        pragmas, "ARRAY_PARTITION", name
                    ),
                    "reshape": _storage_directive(
                        pragmas, "ARRAY_RESHAPE", name
                    ),
                    "access_pattern": _access_pattern(
                        clean,
                        name,
                        declaration_spans,
                        induction_variables,
                    ),
                    "accesses": _array_access_records(
                        clean,
                        name,
                        declaration_spans,
                        internal_loops,
                    ),
                }
            )

        constants = tuple(
            {"name": name, "value": value}
            for name, value in sorted(constant_values.items())
        )
        return DesignMetadata(tuple(loops), tuple(arrays), constants)
    except Exception:
        return DesignMetadata((), (), parse_status="parse_error")


def _lane_stride(
    expression: str,
    induction_variable: str,
    constants: dict[str, int],
) -> int | None:
    """Return the proven affine displacement for one consecutive loop lane."""
    compact = re.sub(r"\s+", "", expression)
    occurrences = re.findall(
        rf"(?<![A-Za-z0-9_]){re.escape(induction_variable)}"
        rf"(?![A-Za-z0-9_])",
        compact,
    )
    if len(occurrences) != 1:
        return None
    token = r"(?:\d+|[A-Za-z_]\w*)"
    multiplied = re.search(
        rf"(?:{re.escape(induction_variable)}\*(?P<rhs>{token})"
        rf"|(?P<lhs>{token})\*{re.escape(induction_variable)})",
        compact,
    )
    if multiplied is None:
        return 1
    raw = multiplied.group("rhs") or multiplied.group("lhs")
    if raw.isdigit():
        value = int(raw)
    else:
        value = constants.get(raw)
    return value if isinstance(value, int) and value > 0 else None


def _cyclic_distinct_banks(
    concurrent_lanes: int,
    lane_stride: int,
    factor: int,
) -> int:
    return min(
        concurrent_lanes,
        factor // math.gcd(factor, lane_stride),
    )


def _block_distinct_bank_lower_bound(
    array_extent: int,
    concurrent_lanes: int,
    lane_stride: int,
    factor: int,
) -> int:
    """Return a base-alignment-independent lower bound on used block banks."""
    block_size = math.ceil(array_extent / factor)
    lane_span = (concurrent_lanes - 1) * lane_stride
    return min(concurrent_lanes, factor, 1 + lane_span // block_size)


def _banking_option_space(
    *,
    dimension: int,
    array_extent: int,
    concurrent_lanes: int,
    lane_stride: int,
) -> dict[str, Any] | None:
    """Describe evidence-supported banking parameters without ranking a trial."""
    factor_limit = min(array_extent, concurrent_lanes)
    if factor_limit < 2:
        return None
    valid_types = []
    for partition_type in ("cyclic", "block"):
        useful = any(
            (
                _cyclic_distinct_banks(
                    concurrent_lanes, lane_stride, factor
                )
                if partition_type == "cyclic"
                else _block_distinct_bank_lower_bound(
                    array_extent,
                    concurrent_lanes,
                    lane_stride,
                    factor,
                )
            )
            > 1
            for factor in range(2, factor_limit + 1)
        )
        if useful:
            valid_types.append(partition_type)
    if not valid_types:
        return None
    return {
        "pragma_classes": (
            ["ARRAY_PARTITION", "ARRAY_RESHAPE"]
            if lane_stride == 1
            else ["ARRAY_PARTITION"]
        ),
        "partition_types": valid_types,
        "factor_min": 2,
        "factor_max": factor_limit,
        "dimension": dimension,
        "selection_rule": (
            "Select a factor/type only when evaluate_source_banking_trial "
            "proves more than one distinct bank for the affine access map; "
            "compare every selected point by measured Q_HW."
        ),
    }


def evaluate_source_banking_trial(
    evidence: dict[str, Any],
    *,
    pragma_class: str,
    partition_type: str,
    factor: int | None,
) -> dict[str, Any]:
    """Validate a proposed storage trial against deterministic access facts."""
    directive = pragma_class.upper()
    kind = partition_type.lower()
    try:
        array_extent = int(evidence["array_extent"])
        concurrent_lanes = int(evidence["concurrent_lanes"])
        lane_stride = int(evidence["lane_stride"])
        factor_limit = int(evidence["factor_limit"])
    except (KeyError, TypeError, ValueError):
        return {
            "supported": False,
            "reason": "source banking evidence is incomplete",
        }

    if directive not in {"ARRAY_PARTITION", "ARRAY_RESHAPE"}:
        return {
            "supported": False,
            "reason": "unsupported source-backed storage directive",
        }
    if directive == "ARRAY_RESHAPE" and not evidence.get("reshape_eligible"):
        return {
            "supported": False,
            "reason": "ARRAY_RESHAPE requires adjacent affine lane accesses",
        }

    if kind == "complete":
        if factor is not None:
            return {
                "supported": False,
                "reason": "complete partition/reshape must omit factor",
            }
        if array_extent > concurrent_lanes:
            return {
                "supported": False,
                "reason": (
                    "complete storage expansion exceeds proven concurrent lanes"
                ),
            }
        return {
            "supported": True,
            "parallel_values": array_extent,
            "collision_free": True,
        }

    if kind not in {"cyclic", "block"}:
        return {
            "supported": False,
            "reason": "partition type must be cyclic, block, or complete",
        }
    if factor is None or factor < 2:
        return {
            "supported": False,
            "reason": "a finite factor >=2 is required",
        }
    if factor > factor_limit:
        return {
            "supported": False,
            "reason": (
                f"factor={factor} exceeds the useful source-derived limit "
                f"{factor_limit} (min(array extent, concurrent lanes))"
            ),
        }

    if directive == "ARRAY_RESHAPE":
        return {
            "supported": True,
            "parallel_values": min(concurrent_lanes, factor),
            "collision_free": factor >= concurrent_lanes,
        }
    if kind == "cyclic":
        distinct_banks = _cyclic_distinct_banks(
            concurrent_lanes,
            lane_stride,
            factor,
        )
    else:
        distinct_banks = _block_distinct_bank_lower_bound(
            array_extent,
            concurrent_lanes,
            lane_stride,
            factor,
        )
    if distinct_banks <= 1:
        return {
            "supported": False,
            "reason": (
                f"{kind} factor={factor} does not provably increase distinct "
                "banks for the affine lane mapping"
            ),
            "distinct_banks": distinct_banks,
        }
    return {
        "supported": True,
        "distinct_banks": distinct_banks,
        "collision_free": distinct_banks >= concurrent_lanes,
    }


def source_supported_banking_evidence(
    metadata: DesignMetadata,
) -> list[dict[str, Any]]:
    """Describe local-array banking option spaces from affine source access.

    Evidence is emitted only for local arrays read by a source-bounded,
    Vitis-auto-parallel loop with a provable affine lane displacement and
    extent.  No type or factor is preferred; the synthesis gate separately
    validates the bank mapping of any proposed trial.
    """
    loops = {
        str(loop.get("label") or loop.get("name") or ""): loop
        for loop in metadata.loops
    }
    constants = {
        str(item.get("name")): int(item["value"])
        for item in metadata.constants
        if item.get("name") and isinstance(item.get("value"), int)
    }
    grouped: dict[
        str,
        list[tuple[dict[str, Any], dict[str, Any], int, int, str]],
    ] = {}
    for array in metadata.arrays:
        if array.get("storage") != "local":
            continue
        if array.get("partition", "none") != "none":
            continue
        for access in array.get("accesses", []):
            if not isinstance(access, dict) or access.get("mode") != "read":
                continue
            loop_name = str(access.get("loop") or "")
            variable = str(access.get("induction_variable") or "")
            dimensions = access.get("dimensions", [])
            if (
                not loop_name
                or loop_name == UNKNOWN
                or not variable
                or variable == UNKNOWN
                or not isinstance(dimensions, list)
            ):
                continue
            for dimension, expression in enumerate(dimensions, start=1):
                stride = _lane_stride(str(expression), variable, constants)
                if stride is not None:
                    grouped.setdefault(loop_name, []).append(
                        (
                            array,
                            access,
                            dimension,
                            stride,
                            str(expression),
                        )
                    )
                    break

    evidence: list[dict[str, Any]] = []
    for loop_name, records in grouped.items():
        distinct_arrays = {
            str(array.get("name") or "")
            for array, _, _, _, _ in records
            if array.get("name")
        }
        loop = loops.get(loop_name, {})
        auto_parallelism = loop.get("auto_parallelism", {})
        concurrent_lanes_proven = bool(
            isinstance(auto_parallelism, dict)
            and (
                auto_parallelism.get("pipeline")
                or auto_parallelism.get("unroll")
                or auto_parallelism.get("pipeline_ancestors")
            )
        )
        if not concurrent_lanes_proven:
            continue
        trip_count = loop.get("trip_count")
        if not isinstance(trip_count, int) or trip_count <= 1:
            continue
        seen_arrays: set[str] = set()
        for array, access, dimension, stride, expression in records:
            name = str(array.get("name") or "")
            if not name or name in seen_arrays:
                continue
            seen_arrays.add(name)
            same_array_records = [
                item
                for item in records
                if str(item[0].get("name") or "") == name
            ]
            access_shapes = {
                (item[2], item[3]) for item in same_array_records
            }
            if len(access_shapes) != 1:
                continue
            extents = array.get("extents", [])
            if not isinstance(extents, list) or dimension > len(extents):
                continue
            array_extent = _positive_int_expression(
                extents[dimension - 1],
                constants,
            )
            if array_extent is None:
                continue
            factor_limit = min(array_extent, trip_count)
            banking_option_space = _banking_option_space(
                dimension=dimension,
                array_extent=array_extent,
                concurrent_lanes=trip_count,
                lane_stride=stride,
            )
            if factor_limit < 2 or banking_option_space is None:
                continue
            evidence.append(
                {
                    "kind": "source_affine_parallel_reads",
                    "array": name,
                    "loop": loop_name,
                    "dimension": dimension,
                    "index_expression": expression,
                    "lane_stride": stride,
                    "array_extent": array_extent,
                    "concurrent_lanes": trip_count,
                    "factor_limit": factor_limit,
                    "banking_option_space": banking_option_space,
                    "reshape_eligible": stride == 1,
                    "banking_model": {
                        "cyclic": "bank=index mod factor",
                        "block": (
                            "bank=floor(index/ceil(array_extent/factor))"
                        ),
                    },
                    "co_read_arrays": sorted(distinct_arrays)[:8],
                    "reason": (
                        f"local array {name} is read with affine lane stride "
                        f"{stride} in auto-parallel compute loop {loop_name}"
                    ),
                }
            )
    return evidence[:8]


def bounded_metadata_payload(
    metadata: DesignMetadata, *, max_chars: int = DEFAULT_METADATA_PROMPT_CHARS
) -> dict[str, Any]:
    """Return a compact deterministic prompt projection with a hard bound.

    ``DesignMetadata.to_dict()`` remains the lossless machine-readable form.
    This projection deliberately removes fields that are redundant for model
    planning so that metadata does not dominate the optimization prompt.
    """
    limit = max(128, int(max_chars))
    source = metadata.to_dict()
    payload: dict[str, Any] = {
        "parse_status": source["parse_status"],
        "loop_count": len(source["loops"]),
        "array_count": len(source["arrays"]),
        "loops": [],
        "arrays": [],
        "truncated": bool(source["truncated"]),
    }

    def text(value: Any, bound: int = 80) -> Any:
        if not isinstance(value, str) or len(value) <= bound:
            return value
        return value[: bound - 3].rstrip() + "..."

    def loop_projection(item: dict[str, Any]) -> dict[str, Any]:
        pipeline = item.get("pipeline")
        unroll = item.get("unroll")
        return {
            "name": text(item.get("name", UNKNOWN)),
            "nesting_depth": item.get("nesting_depth", UNKNOWN),
            "lower_bound": text(item.get("lower_bound", UNKNOWN)),
            "upper_bound": text(item.get("upper_bound", UNKNOWN)),
            "step": text(item.get("step", UNKNOWN), 24),
            "trip_count": item.get("trip_count", UNKNOWN),
            "pipeline_ii": (
                pipeline.get("ii", UNKNOWN)
                if isinstance(pipeline, dict) and pipeline.get("enabled")
                else "none"
            ),
            "unroll_factor": (
                unroll.get("factor", UNKNOWN)
                if isinstance(unroll, dict) and unroll.get("enabled")
                else "none"
            ),
            "report_loop_name": text(
                item.get("report_loop_name", UNKNOWN)
            ),
            "vitis_inferred": list(
                item.get("vitis_inferred_directives", [])
            )[:4],
            "auto_parallelism": item.get("auto_parallelism", {}),
        }

    def array_projection(item: dict[str, Any]) -> dict[str, Any]:
        extents = item.get("extents", [])
        if not isinstance(extents, list):
            extents = [UNKNOWN]
        return {
            "name": text(item.get("name", UNKNOWN)),
            "element_type": text(item.get("element_type", UNKNOWN), 64),
            "rank": item.get("rank", UNKNOWN),
            "extents": [text(value, 40) for value in extents[:4]],
            "storage": item.get("storage", UNKNOWN),
            "partition": item.get("partition", "none"),
            "reshape": item.get("reshape", "none"),
            "access_pattern": item.get(
                "access_pattern", {"kind": UNKNOWN, "stride": UNKNOWN}
            ),
        }

    def size(value: dict[str, Any]) -> int:
        return len(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        )

    projections = {
        "loops": [loop_projection(item) for item in source["loops"]],
        "arrays": [array_projection(item) for item in source["arrays"]],
    }
    # Round-robin keeps both loop and array evidence visible under tight
    # limits instead of letting a long loop list consume the whole budget.
    next_index = {"loops": 0, "arrays": 0}
    made_progress = True
    while made_progress:
        made_progress = False
        for section in ("loops", "arrays"):
            index = next_index[section]
            if index >= len(projections[section]):
                continue
            item = projections[section][index]
            trial = {
                **payload,
                section: [*payload[section], item],
            }
            if size(trial) <= limit:
                payload[section].append(item)
                next_index[section] += 1
                made_progress = True
            else:
                next_index[section] = len(projections[section])
                payload["truncated"] = True
        if all(
            next_index[section] >= len(projections[section])
            for section in ("loops", "arrays")
        ):
            break
    if any(
        len(payload[section]) < len(source[section])
        for section in ("loops", "arrays")
    ):
        payload["truncated"] = True
    return payload
