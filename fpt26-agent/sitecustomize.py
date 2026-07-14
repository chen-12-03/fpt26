from __future__ import annotations

import ast
import sys
import types
from typing import Any


try:
    import tomllib as _stdlib_tomllib  # noqa: F401
except ModuleNotFoundError:

    def _strip_comment(line: str) -> str:
        in_string = False
        escaped = False
        for index, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == "\\" and in_string:
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if char == "#" and not in_string:
                return line[:index]
        return line

    def _parse_value(value: str) -> Any:
        raw = value.strip()
        if raw == "true":
            return True
        if raw == "false":
            return False
        if raw.startswith('"') or raw.startswith("["):
            return ast.literal_eval(raw)
        try:
            return int(raw)
        except ValueError:
            return float(raw)

    def loads(data: str, /, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if args or kwargs:
            raise TypeError("compat tomllib.loads accepts only the TOML string")
        root: dict[str, Any] = {}
        current = root
        for line_number, line in enumerate(data.splitlines(), start=1):
            stripped = _strip_comment(line).strip()
            if not stripped:
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip()
                if not section:
                    raise ValueError(f"empty TOML section at line {line_number}")
                current = root.setdefault(section, {})
                if not isinstance(current, dict):
                    raise ValueError(f"TOML section conflicts with key: {section}")
                continue
            if "=" not in stripped:
                raise ValueError(f"invalid TOML line {line_number}: {line!r}")
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key:
                raise ValueError(f"empty TOML key at line {line_number}")
            current[key] = _parse_value(value)
        return root

    def load(file_obj: Any, /, *args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = file_obj.read()
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return loads(payload, *args, **kwargs)

    compat_tomllib = types.ModuleType("tomllib")
    compat_tomllib.loads = loads
    compat_tomllib.load = load
    compat_tomllib.TOMLDecodeError = ValueError
    sys.modules["tomllib"] = compat_tomllib
