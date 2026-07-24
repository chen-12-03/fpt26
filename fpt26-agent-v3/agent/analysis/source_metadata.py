"""Deterministic, conservative source metadata for optimization prompts.

This module intentionally implements a small C/C++ recognizer rather than a
compiler.  It reports only syntax that can be identified unambiguously and
uses ``"unknown"`` for everything else.  Parse failures never escape into the
optimization workflow.
"""

from __future__ import annotations

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
_POINTER_PARAM_RE = re.compile(
    r"^\s*(?P<type>"
    r"(?:(?:const|volatile|unsigned|signed|long|short)\s+)*"
    r"[A-Za-z_]\w*(?:::\w+)*(?:\s*<[^>]+>)?"
    r")\s*\*+\s*(?P<name>[A-Za-z_]\w*)\s*$"
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


@dataclass(frozen=True)
class DesignMetadata:
    loops: tuple[dict[str, Any], ...]
    arrays: tuple[dict[str, Any], ...]
    parse_status: str = "ok"
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "parse_status": self.parse_status,
            "loops": [dict(item) for item in self.loops],
            "arrays": [dict(item) for item in self.arrays],
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
    source: Any, *, loop_metrics: Iterable[dict[str, Any]] | None = None
) -> DesignMetadata:
    """Extract stable loop/array metadata; return an empty result on failure."""
    text = _safe_text(source)
    if not text.strip():
        return DesignMetadata((), (), parse_status="empty")
    try:
        clean = _mask_comments_and_strings(text)
        pragmas = _directive_pragmas(clean)
        metrics = [dict(item) for item in (loop_metrics or [])]

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
            header = _loop_header(
                match.group("init"),
                match.group("condition"),
                match.group("increment"),
            )
            internal_loops.append(
                {
                    "_start": match.start(),
                    "_body_open": body_open,
                    "_body_end": body_end,
                    "_index": index,
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
                    "pipeline": pipeline,
                    "unroll": unroll,
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
            arrays.append(
                {
                    "name": name,
                    "element_type": re.sub(
                        r"\s+", " ", match.group("type")
                    ).strip(),
                    "rank": len(extents),
                    "extents": extents,
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
                }
            )

        return DesignMetadata(tuple(loops), tuple(arrays))
    except Exception:
        return DesignMetadata((), (), parse_status="parse_error")


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
