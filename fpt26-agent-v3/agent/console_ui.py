"""Small, dependency-free console UI for interactive agent runs."""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
from typing import TextIO


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_COLOR_POLICY = "auto"


class _Color:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    RED = "\x1b[31m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    BLUE = "\x1b[34m"
    MAGENTA = "\x1b[35m"
    CYAN = "\x1b[36m"
    WHITE = "\x1b[37m"


def configure(color: str = "auto") -> None:
    """Configure ANSI output for the current process."""
    if color not in {"auto", "always", "never"}:
        raise ValueError(f"invalid color policy: {color}")
    global _COLOR_POLICY
    _COLOR_POLICY = color


def color_enabled(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    if _COLOR_POLICY == "always":
        return True
    if _COLOR_POLICY == "never" or os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR", "").strip() not in {"", "0"}:
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def paint(text: object, *codes: str, stream: TextIO | None = None) -> str:
    value = str(text)
    if not codes or not color_enabled(stream):
        return value
    return f"{''.join(codes)}{value}{_Color.RESET}"


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def console_width() -> int:
    """Return a stable readable width, even when stdout is piped through tee."""
    configured = os.environ.get("FPT26_CONSOLE_WIDTH", "").strip()
    if configured.isdigit():
        return min(max(int(configured), 72), 112)
    return min(max(shutil.get_terminal_size((96, 24)).columns, 72), 112)


def _progress_kind(message: str) -> tuple[str, str, str]:
    lower = message.lstrip().lower()
    if lower.startswith("task="):
        return "RUN", "●", _Color.CYAN
    if lower.startswith("csim"):
        return "CSIM", "✓" if "pass" in lower else "×", _Color.GREEN if "pass" in lower else _Color.RED
    if lower.startswith("synth"):
        if "fail" in lower:
            return "SYNTH", "×", _Color.RED
        return "SYNTH", "✓" if "pass" in lower else "◆", _Color.GREEN if "pass" in lower else _Color.BLUE
    if lower.startswith("cosim"):
        return "COSIM", "✓" if "pass" in lower else "×", _Color.GREEN if "pass" in lower else _Color.RED
    if "interface gate" in lower or " gate " in lower:
        return "GATE", "×" if "fail" in lower else "✓", _Color.RED if "fail" in lower else _Color.GREEN
    if lower.startswith("opt") or lower.startswith("optimize"):
        return "OPT", "◆", _Color.MAGENTA
    if lower.startswith("repair") or lower.startswith("structural"):
        return "REPAIR", "◆", _Color.YELLOW
    if lower.startswith("final kernel"):
        return "SAVE", "✓", _Color.GREEN
    if lower.startswith("•"):
        return "INSIGHT", "·", _Color.YELLOW
    return "AGENT", "·", _Color.BLUE


def _clean_progress_message(message: str) -> str:
    cleaned = message.strip()
    if cleaned.startswith("•"):
        cleaned = cleaned[1:].strip()
    cleaned = re.sub(
        r"^(csim|synth|cosim):\s*\[\1\]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^\[(csim|synth|cosim)]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " · ", cleaned)
    cleaned = re.sub(r"\bpass\b", "PASS", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bfail\b", "FAIL", cleaned, flags=re.IGNORECASE)
    return cleaned


def progress(mode: str, message: str) -> None:
    """Render a classified, wrapped progress event."""
    tag, symbol, color = _progress_kind(message)
    content = _clean_progress_message(message)
    prefix_plain = f"  {symbol} {tag:<8} "
    prefix = f"  {paint(symbol, _Color.BOLD, color)} {paint(f'{tag:<8}', _Color.BOLD, color)} "
    available = max(console_width() - len(prefix_plain), 30)
    lines = textwrap.wrap(
        content,
        width=available,
        break_long_words=False,
        break_on_hyphens=False,
        subsequent_indent="",
    ) or [""]
    tone = _Color.RED if "FAIL" in content else (_Color.GREEN if "PASS" in content else _Color.WHITE)
    print(prefix + paint(lines[0], tone), flush=True)
    continuation = " " * len(prefix_plain)
    for line in lines[1:]:
        print(continuation + paint(line, _Color.DIM), flush=True)


def run_header(*, task_id: str, task_type: str, mode: str, backend: str, budget: int, output_root: str) -> None:
    width = console_width()
    title = " FPT26 · HLS OPTIMIZATION AGENT "
    print()
    print(paint("╭" + title + "─" * max(width - len(title) - 2, 0) + "╮", _Color.BOLD, _Color.CYAN))
    items = (
        ("Task", task_id),
        ("Profile", f"{task_type} · {mode.upper()} · backend={backend}"),
        ("Budget", f"{budget} credits"),
        ("Output", output_root),
    )
    for label, value in items:
        body = f"{label:<10}{value}"
        visible = min(len(body), width - 4)
        print("│ " + paint(f"{label:<10}", _Color.BOLD, _Color.CYAN) + str(value)[: width - 14] + " " * max(width - visible - 3, 0) + "│")
    print(paint("╰" + "─" * (width - 2) + "╯", _Color.CYAN))
    print()


def artifact(label: str, path: object) -> None:
    print(f"  {paint('✓', _Color.GREEN, _Color.BOLD)} {paint(label + ':', _Color.BOLD)} {path}")


def error(message: str, *, stream: TextIO | None = None) -> None:
    stream = stream or sys.stderr
    print(f"{paint('ERROR', _Color.RED, _Color.BOLD, stream=stream)}  {message}", file=stream)


# Kept private so renderers can share one palette without exposing ANSI details.
Color = _Color
