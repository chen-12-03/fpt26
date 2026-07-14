#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.ir import HLSIR, load_ir


KERNEL_FILENAME = "kernel.cpp"
HOST_FILENAME = "host.cpp"
SUPPORTED_OPERATION = "vector_add"
SUPPORTED_DATA_TYPE = "int"
SIZE_CONSTANT = "VECTOR_ADD_SIZE"
C_RESERVED_WORDS = {
    "auto",
    "bool",
    "break",
    "case",
    "catch",
    "char",
    "class",
    "const",
    "continue",
    "default",
    "delete",
    "do",
    "double",
    "else",
    "enum",
    "extern",
    "false",
    "float",
    "for",
    "if",
    "int",
    "long",
    "main",
    "namespace",
    "new",
    "private",
    "protected",
    "public",
    "return",
    "short",
    "signed",
    "sizeof",
    "static",
    "struct",
    "switch",
    "template",
    "true",
    "try",
    "typedef",
    "unsigned",
    "void",
    "while",
    "VECTOR_ADD_SIZE",
    "expected_output",
    "errors",
    "i",
}


class TemplateGenerationError(Exception):
    """Raised when an IR cannot be materialized by a deterministic template."""


@dataclass(frozen=True)
class GeneratedTemplate:
    kernel_path: Path
    host_path: Path
    top_function: str
    function_signature: str


@dataclass(frozen=True)
class VectorAddSpec:
    top_function: str
    input_a: str
    input_b: str
    output: str
    data_type: str
    length: int


def generate_vector_add_template(
    ir_path: str | Path,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> GeneratedTemplate:
    ir = load_ir(ir_path)
    spec = _validate_vector_add_ir(ir)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    kernel_path = output_path / KERNEL_FILENAME
    host_path = output_path / HOST_FILENAME
    _ensure_writable_outputs([kernel_path, host_path], overwrite=overwrite)

    kernel_text = _render_kernel(spec)
    host_text = _render_host(spec)
    kernel_path.write_text(kernel_text, encoding="utf-8")
    host_path.write_text(host_text, encoding="utf-8")

    return GeneratedTemplate(
        kernel_path=kernel_path,
        host_path=host_path,
        top_function=spec.top_function,
        function_signature=_function_signature(spec),
    )


def _validate_vector_add_ir(ir: HLSIR) -> VectorAddSpec:
    if ir.input_mode != "natural_language":
        raise TemplateGenerationError(
            f"template generation requires input_mode 'natural_language', got {ir.input_mode!r}"
        )

    operation = _operation_from_ir(ir)
    if operation != SUPPORTED_OPERATION:
        raise TemplateGenerationError(f"unsupported operation: {operation!r}; only 'vector_add' is supported")

    _require_identifier(ir.top_function, "top_function")
    if len(ir.inputs) != 2:
        raise TemplateGenerationError("vector_add template requires exactly 2 input arrays")
    if len(ir.outputs) != 1:
        raise TemplateGenerationError("vector_add template requires exactly 1 output array")

    ports = [*ir.inputs, *ir.outputs]
    for index, port in enumerate(ports):
        label = f"port[{index}]"
        _require_identifier(_port_name(port, label), f"{label}.name")
        data_type = port.get("data_type")
        if data_type != SUPPORTED_DATA_TYPE:
            raise TemplateGenerationError(
                f"unsupported data type for {label}: {data_type!r}; only 'int' is supported"
            )

    shapes = [_port_shape(port, f"port[{index}]") for index, port in enumerate(ports)]
    first_shape = shapes[0]
    for shape in shapes[1:]:
        if shape != first_shape:
            raise TemplateGenerationError("vector_add input and output shapes must match exactly")
    if len(first_shape) != 1:
        raise TemplateGenerationError("vector_add template only supports one-dimensional arrays")
    length = first_shape[0]
    if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
        raise TemplateGenerationError("vector_add shape must be a positive integer length")

    names = [_port_name(port, f"port[{index}]") for index, port in enumerate(ports)]
    if len(set(names)) != len(names):
        raise TemplateGenerationError("vector_add port names must be unique")

    return VectorAddSpec(
        top_function=ir.top_function,
        input_a=names[0],
        input_b=names[1],
        output=names[2],
        data_type=SUPPORTED_DATA_TYPE,
        length=length,
    )


def _operation_from_ir(ir: HLSIR) -> str:
    operation = ir.inferred_fields.get("operation")
    if isinstance(operation, str):
        return operation
    if isinstance(operation, dict):
        value = operation.get("value")
        if isinstance(value, str):
            return value
    return ir.task_id


def _port_name(port: dict[str, Any], label: str) -> str:
    value = port.get("name")
    if not isinstance(value, str) or not value:
        raise TemplateGenerationError(f"{label}.name must be a non-empty string")
    return value


def _port_shape(port: dict[str, Any], label: str) -> list[Any]:
    value = port.get("shape")
    if not isinstance(value, list):
        raise TemplateGenerationError(f"{label}.shape must be a list")
    return value


def _require_identifier(value: str, label: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise TemplateGenerationError(f"{label} must be a valid C identifier")
    if value in C_RESERVED_WORDS:
        raise TemplateGenerationError(f"{label} must not be a reserved C/C++ keyword")


def _ensure_writable_outputs(paths: list[Path], *, overwrite: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not overwrite:
        names = ", ".join(str(path) for path in existing)
        raise TemplateGenerationError(f"refusing to overwrite existing output file(s): {names}")


def _function_signature(spec: VectorAddSpec) -> str:
    return (
        f'extern "C" void {spec.top_function}('
        f"const {spec.data_type} {spec.input_a}[{SIZE_CONSTANT}], "
        f"const {spec.data_type} {spec.input_b}[{SIZE_CONSTANT}], "
        f"{spec.data_type} {spec.output}[{SIZE_CONSTANT}])"
    )


def _render_kernel(spec: VectorAddSpec) -> str:
    return f"""static const int {SIZE_CONSTANT} = {spec.length};

extern "C" void {spec.top_function}(
    const {spec.data_type} {spec.input_a}[{SIZE_CONSTANT}],
    const {spec.data_type} {spec.input_b}[{SIZE_CONSTANT}],
    {spec.data_type} {spec.output}[{SIZE_CONSTANT}]
)
{{
    for (int i = 0; i < {SIZE_CONSTANT}; ++i) {{
        {spec.output}[i] = {spec.input_a}[i] + {spec.input_b}[i];
    }}
}}
"""


def _render_host(spec: VectorAddSpec) -> str:
    input_a_data = f"{spec.input_a}_data"
    input_b_data = f"{spec.input_b}_data"
    output_data = f"{spec.output}_data"
    return f"""#include <cstdio>

static const int {SIZE_CONSTANT} = {spec.length};

extern "C" void {spec.top_function}(
    const {spec.data_type} {spec.input_a}[{SIZE_CONSTANT}],
    const {spec.data_type} {spec.input_b}[{SIZE_CONSTANT}],
    {spec.data_type} {spec.output}[{SIZE_CONSTANT}]
);

int main()
{{
    {spec.data_type} {input_a_data}[{SIZE_CONSTANT}];
    {spec.data_type} {input_b_data}[{SIZE_CONSTANT}];
    {spec.data_type} {output_data}[{SIZE_CONSTANT}];
    {spec.data_type} expected_output[{SIZE_CONSTANT}];

    for (int i = 0; i < {SIZE_CONSTANT}; ++i) {{
        {input_a_data}[i] = (i * 3) - 7;
        {input_b_data}[i] = 42 - (i * 2);
        {output_data}[i] = 0;
        expected_output[i] = {input_a_data}[i] + {input_b_data}[i];
    }}

    {spec.top_function}({input_a_data}, {input_b_data}, {output_data});

    int errors = 0;
    for (int i = 0; i < {SIZE_CONSTANT}; ++i) {{
        if ({output_data}[i] != expected_output[i]) {{
            std::printf(
                "Mismatch at index %d: got %d, expected %d\\n",
                i,
                {output_data}[i],
                expected_output[i]
            );
            ++errors;
        }}
    }}

    if (errors != 0) {{
        std::printf("vector_add failed: %d mismatches\\n", errors);
        return 1;
    }}

    std::printf("vector_add passed: %d elements checked\\n", {SIZE_CONSTANT});
    return 0;
}}
"""
