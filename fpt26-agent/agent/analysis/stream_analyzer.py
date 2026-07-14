from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.core.task_context import TaskContext


@dataclass(frozen=True)
class StreamAnalysis:
    status: str
    stream_declarations: list[dict[str, Any]]
    stream_element_types: dict[str, str | None]
    stream_depth_pragmas: list[dict[str, Any]]
    producer_functions: dict[str, list[dict[str, Any]]]
    consumer_functions: dict[str, list[dict[str, Any]]]
    read_sites: list[dict[str, Any]]
    write_sites: list[dict[str, Any]]
    dataflow_regions: list[dict[str, Any]]
    constant_read_write_counts: dict[str, dict[str, Any]]
    possible_producer_consumer_imbalance: list[dict[str, Any]]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stream_declarations": _json_value(self.stream_declarations),
            "stream_element_types": _json_value(self.stream_element_types),
            "stream_depth_pragmas": _json_value(self.stream_depth_pragmas),
            "producer_functions": _json_value(self.producer_functions),
            "consumer_functions": _json_value(self.consumer_functions),
            "read_sites": _json_value(self.read_sites),
            "write_sites": _json_value(self.write_sites),
            "dataflow_regions": _json_value(self.dataflow_regions),
            "constant_read_write_counts": _json_value(self.constant_read_write_counts),
            "possible_producer_consumer_imbalance": _json_value(self.possible_producer_consumer_imbalance),
            "warnings": list(self.warnings),
        }


class StreamAnalyzer:
    def analyze(self, task_context: TaskContext, kernel_code: str) -> StreamAnalysis:
        stripped = _strip_comments(kernel_code)
        functions = _functions(stripped)
        stream_declarations = _stream_declarations(stripped, functions)
        stream_element_types = {
            item["name"]: item.get("element_type") for item in stream_declarations if isinstance(item.get("name"), str)
        }
        stream_depth_pragmas = _stream_depth_pragmas(stripped)
        read_sites, write_sites = _read_write_sites(stripped, functions)
        dataflow_regions = _dataflow_regions(stripped, functions, task_context.top_function)
        param_summaries = _function_stream_params(functions)
        call_links = _dataflow_call_links(functions, dataflow_regions, param_summaries)
        producer_functions, consumer_functions, counts = _producer_consumer_maps(call_links)
        imbalance = _imbalance_hints(stream_declarations, producer_functions, consumer_functions, counts, functions)
        warnings: list[str] = []
        if stream_declarations and not dataflow_regions:
            warnings.append("hls::stream declarations found but no DATAFLOW pragma region was identified")
        if not stream_declarations:
            warnings.append("no hls::stream declarations were identified")
        status = "pass" if stream_declarations or read_sites or write_sites else "unknown"
        return StreamAnalysis(
            status=status,
            stream_declarations=stream_declarations,
            stream_element_types=stream_element_types,
            stream_depth_pragmas=stream_depth_pragmas,
            producer_functions=producer_functions,
            consumer_functions=consumer_functions,
            read_sites=read_sites,
            write_sites=write_sites,
            dataflow_regions=dataflow_regions,
            constant_read_write_counts=counts,
            possible_producer_consumer_imbalance=imbalance,
            warnings=warnings,
        )


def _strip_comments(code: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    return re.sub(r"//.*", "", no_block)


def _functions(code: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"(?P<prefix>(?:static\s+|inline\s+|extern\s+)*[A-Za-z_][\w:<>,\s*&~]*?)"
        r"\b(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^;{}()]*(?:\([^)]*\)[^;{}()]*)*)\)\s*\{",
        re.MULTILINE,
    )
    functions: list[dict[str, Any]] = []
    for match in pattern.finditer(code):
        name = match.group("name")
        if name in {"if", "for", "while", "switch"}:
            continue
        open_brace = code.find("{", match.end() - 1)
        close_brace = _matching_brace(code, open_brace)
        if close_brace is None:
            continue
        functions.append(
            {
                "name": name,
                "signature": re.sub(r"\s+", " ", match.group(0)[:-1].strip()),
                "params": match.group("params"),
                "body": code[open_brace + 1 : close_brace],
                "start": match.start(),
                "body_start": open_brace + 1,
                "end": close_brace,
            }
        )
    return functions


def _matching_brace(text: str, open_brace: int) -> int | None:
    if open_brace < 0:
        return None
    depth = 0
    for index in range(open_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _stream_declarations(code: str, functions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    pattern = re.compile(r"hls::stream\s*<\s*([^>]+?)\s*>\s+([^\n;()]+);")
    for match in pattern.finditer(code):
        element_type = re.sub(r"\s+", " ", match.group(1).strip())
        scope = _scope_name(functions, match.start())
        for name in _declarator_names(match.group(2)):
            declarations.append(
                {
                    "name": name,
                    "element_type": element_type,
                    "scope": scope or "unknown",
                    "depth": _depth_for_stream(code, name),
                }
            )
    return declarations


def _declarator_names(text: str) -> list[str]:
    names: list[str] = []
    for part in text.split(","):
        item = part.strip()
        match = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?$", item)
        if match:
            names.append(match.group(1))
    return names


def _stream_depth_pragmas(code: str) -> list[dict[str, Any]]:
    pragmas: list[dict[str, Any]] = []
    pattern = re.compile(r"#\s*pragma\s+HLS\s+STREAM[^\n]*", re.IGNORECASE)
    for match in pattern.finditer(code):
        line = match.group(0).strip()
        variable = _pragma_value(line, "variable")
        depth = _pragma_value(line, "depth")
        pragmas.append({"pragma": line, "variable": variable, "depth": depth})
    return pragmas


def _depth_for_stream(code: str, stream_name: str) -> str | None:
    pattern = re.compile(
        r"#\s*pragma\s+HLS\s+STREAM[^\n]*\bvariable\s*=\s*"
        + re.escape(stream_name)
        + r"\b[^\n]*",
        re.IGNORECASE,
    )
    match = pattern.search(code)
    if not match:
        return None
    return _pragma_value(match.group(0), "depth")


def _pragma_value(line: str, key: str) -> str | None:
    match = re.search(r"\b" + re.escape(key) + r"\s*=\s*([A-Za-z_]\w*|\d+)", line)
    return match.group(1) if match else None


def _scope_name(functions: list[dict[str, Any]], index: int) -> str | None:
    for function in functions:
        if function["body_start"] <= index <= function["end"]:
            return function["name"]
    return None


def _read_write_sites(code: str, functions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reads: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\.\s*(read|write)\s*\(", code):
        site = {
            "stream": match.group(1),
            "function": _scope_name(functions, match.start()) or "unknown",
            "operation": match.group(2),
            "count": _enclosing_loop_bound(code, match.start()) or "unknown",
        }
        if match.group(2) == "read":
            reads.append(site)
        else:
            writes.append(site)
    return reads, writes


def _enclosing_loop_bound(code: str, index: int) -> str | None:
    prefix = code[:index]
    matches = list(re.finditer(r"for\s*\([^;]*;\s*([A-Za-z_]\w*)\s*(?:<|<=)\s*([A-Za-z_]\w*|\d+)\s*;", prefix))
    if not matches:
        return None
    return matches[-1].group(2)


def _dataflow_regions(code: str, functions: list[dict[str, Any]], top_function: str) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for function in functions:
        body = function["body"]
        if re.search(r"#\s*pragma\s+HLS\s+DATAFLOW\b", body, flags=re.IGNORECASE):
            regions.append(
                {
                    "function": function["name"],
                    "is_top": function["name"] == top_function,
                    "calls": _function_calls(body),
                    "status": "identified",
                }
            )
    return regions


def _function_calls(body: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*;", body):
        name = match.group(1)
        if name in {"if", "for", "while", "switch", "return"}:
            continue
        calls.append({"callee": name, "args": _split_args(match.group(2))})
    return calls


def _split_args(args: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in args:
        if char in "(<[":
            depth += 1
        elif char in ")>]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _function_stream_params(functions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    summaries: dict[str, list[dict[str, Any]]] = {}
    for function in functions:
        params = _split_args(function["params"])
        stream_params: list[dict[str, Any]] = []
        for index, param in enumerate(params):
            match = re.search(r"hls::stream\s*<\s*([^>]+?)\s*>\s*&?\s*([A-Za-z_]\w*)\b", param)
            if not match:
                continue
            name = match.group(2)
            stream_params.append(
                {
                    "param_index": index,
                    "param": name,
                    "element_type": re.sub(r"\s+", " ", match.group(1).strip()),
                    "reads": _op_count(function["body"], name, "read"),
                    "writes": _op_count(function["body"], name, "write"),
                    "direction": _direction(function["body"], name),
                }
            )
        summaries[function["name"]] = stream_params
    return summaries


def _op_count(body: str, stream_name: str, op: str) -> str:
    if re.search(r"\b" + re.escape(stream_name) + r"\s*\.\s*" + op + r"\s*\(", body) is None:
        return "0"
    counts: set[str] = set()
    for match in re.finditer(r"\b" + re.escape(stream_name) + r"\s*\.\s*" + op + r"\s*\(", body):
        counts.add(_enclosing_loop_bound(body, match.start()) or "unknown")
    if len(counts) == 1:
        return next(iter(counts))
    return "unknown"


def _direction(body: str, stream_name: str) -> str:
    reads = re.search(r"\b" + re.escape(stream_name) + r"\s*\.\s*read\s*\(", body) is not None
    writes = re.search(r"\b" + re.escape(stream_name) + r"\s*\.\s*write\s*\(", body) is not None
    if reads and writes:
        return "read_write"
    if reads:
        return "consumer"
    if writes:
        return "producer"
    return "unknown"


def _dataflow_call_links(
    functions: list[dict[str, Any]],
    dataflow_regions: list[dict[str, Any]],
    param_summaries: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    known_functions = {function["name"] for function in functions}
    for region in dataflow_regions:
        for call in region["calls"]:
            callee = call["callee"]
            if callee not in known_functions:
                continue
            params = param_summaries.get(callee, [])
            for param in params:
                index = param["param_index"]
                actual = call["args"][index] if index < len(call["args"]) else "unknown"
                links.append({"stream": actual, "function": callee, **param})
    return links


def _producer_consumer_maps(
    links: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    producers: dict[str, list[dict[str, Any]]] = {}
    consumers: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, dict[str, Any]] = {}
    for link in links:
        stream = link["stream"]
        entry = {"function": link["function"], "param": link["param"], "count": None}
        if link["writes"] != "0":
            producers.setdefault(stream, []).append({**entry, "count": link["writes"]})
        if link["reads"] != "0":
            consumers.setdefault(stream, []).append({**entry, "count": link["reads"]})
        counts.setdefault(stream, {"reads": [], "writes": []})
        if link["reads"] != "0":
            counts[stream]["reads"].append({"function": link["function"], "count": link["reads"]})
        if link["writes"] != "0":
            counts[stream]["writes"].append({"function": link["function"], "count": link["writes"]})
    return producers, consumers, counts


def _imbalance_hints(
    declarations: list[dict[str, Any]],
    producers: dict[str, list[dict[str, Any]]],
    consumers: dict[str, list[dict[str, Any]]],
    counts: dict[str, dict[str, Any]],
    functions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    declared = {item["name"] for item in declarations}
    for stream in sorted(declared | set(producers) | set(consumers)):
        if not producers.get(stream):
            hints.append({"stream": stream, "kind": "missing_producer", "confidence": "medium"})
        if not consumers.get(stream):
            hints.append({"stream": stream, "kind": "missing_consumer", "confidence": "medium"})
        read_counts = {item["count"] for item in counts.get(stream, {}).get("reads", [])}
        write_counts = {item["count"] for item in counts.get(stream, {}).get("writes", [])}
        if read_counts and write_counts and "unknown" not in read_counts | write_counts and read_counts != write_counts:
            hints.append(
                {
                    "stream": stream,
                    "kind": "constant_read_write_count_mismatch",
                    "read_counts": sorted(read_counts),
                    "write_counts": sorted(write_counts),
                    "confidence": "medium",
                }
            )
    for function in functions:
        bursts = _separate_stream_write_loops(function["body"])
        if len(bursts) > 1:
            hints.append(
                {
                    "function": function["name"],
                    "kind": "separate_stream_write_loops",
                    "streams": bursts,
                    "confidence": "low",
                }
            )
    return hints


def _separate_stream_write_loops(body: str) -> list[str]:
    streams: list[str] = []
    for snippet in _for_loop_snippets(body):
        writes = sorted(set(re.findall(r"\b([A-Za-z_]\w*)\s*\.\s*write\s*\(", snippet)))
        if len(writes) == 1:
            streams.extend(writes)
    return sorted(dict.fromkeys(streams))


def _for_loop_snippets(body: str) -> list[str]:
    snippets: list[str] = []
    for match in re.finditer(r"for\s*\([^)]*\)\s*", body):
        start = match.start()
        cursor = match.end()
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if cursor < len(body) and body[cursor] == "{":
            end = _matching_brace(body, cursor)
            snippets.append(body[start : end + 1] if end is not None else body[start:])
            continue
        end = body.find(";", cursor)
        snippets.append(body[start : end + 1] if end >= 0 else body[start:])
    return snippets


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
