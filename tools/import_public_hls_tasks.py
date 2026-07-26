#!/usr/bin/env python3
"""Import public AMD HLS examples into the local generated task format."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


U55C_PART = "xcu55c-fsvh2892-2L-e"
CLOCK_NS = 5.0
DATA_SUFFIXES = {
    ".data",
    ".dat",
    ".txt",
    ".golden",
    ".in",
    ".out",
    ".hex",
    ".coe",
    ".mif",
}


@dataclass(frozen=True)
class Candidate:
    suite: str
    repo_url: str
    commit: str
    license: str
    source_root: Path
    source_dir: Path
    task_id: str
    top: str
    kernel_sources: tuple[Path, ...]
    tb_source: Path | None
    headers: tuple[Path, ...]
    data_files: tuple[Path, ...]
    generated_tb: bool = False

    @property
    def source_rel(self) -> str:
        return self.source_dir.relative_to(self.source_root).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intro-root", type=Path, required=True)
    parser.add_argument("--accel-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, default=Path("tasks/generated"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tasks/generated/public_hls_tasks_manifest.json"),
    )
    parser.add_argument("--limit", type=int, default=130)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--no-tripcount-pragmas",
        action="store_true",
        help=(
            "Legacy mode: do not add LOOP_TRIPCOUNT pragmas before "
            "variable-bound public loops."
        ),
    )
    args = parser.parse_args()

    existing_ids = {p.parent.name for p in args.out_root.glob("*/task.toml")}
    existing_hashes = _existing_source_hashes(args.out_root)

    candidates = _intro_candidates(args.intro_root) + _accel_candidates(args.accel_root)
    imported: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    seen_ids = set(existing_ids)
    seen_hashes = set(existing_hashes)
    for cand in candidates:
        source_hash = _candidate_hash(cand)
        if cand.task_id in seen_ids:
            skipped.append({"task_id": cand.task_id, "reason": "duplicate_task_id"})
            continue
        if source_hash in seen_hashes:
            skipped.append({"task_id": cand.task_id, "reason": "duplicate_source_hash"})
            continue
        tripcount_count = _write_task(
            cand,
            args.out_root,
            source_hash,
            replace=args.replace,
            inject_tripcount_pragmas=not args.no_tripcount_pragmas,
        )
        seen_ids.add(cand.task_id)
        seen_hashes.add(source_hash)
        imported.append(_manifest_record(cand, source_hash, tripcount_count))
        if len(imported) >= args.limit:
            break

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "public_hls_task_import",
                "imported_count": len(imported),
                "skipped_count": len(skipped),
                "sources": {
                    "amd_intro": {
                        "repo_url": "https://github.com/Xilinx/Vitis-HLS-Introductory-Examples",
                        "commit": _git(args.intro_root, "rev-parse", "HEAD"),
                        "license": "Apache-2.0",
                    },
                    "amd_accel": {
                        "repo_url": "https://github.com/Xilinx/Vitis_Accel_Examples",
                        "commit": _git(args.accel_root, "rev-parse", "HEAD"),
                        "license": "MIT",
                    },
                },
                "imported": imported,
                "skipped": skipped,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"imported={len(imported)} skipped={len(skipped)} manifest={args.manifest}")
    return 0


def _intro_candidates(root: Path) -> list[Candidate]:
    commit = _git(root, "rev-parse", "HEAD")
    candidates = []
    for tcl in sorted(root.rglob("run_hls.tcl")):
        source_dir = tcl.parent
        top = _top_from_tcl(tcl)
        if not top:
            continue
        files = [
            p
            for p in sorted(source_dir.iterdir())
            if p.is_file() and p.suffix.lower() in {".c", ".cc", ".cpp", ".h", ".hpp"}
        ]
        tb = _choose_tb(files)
        kernel_sources = tuple(
            p
            for p in files
            if p.suffix.lower() in {".c", ".cc", ".cpp"} and p != tb
        )
        headers = tuple(p for p in files if p.suffix.lower() in {".h", ".hpp"})
        if not tb or not kernel_sources:
            continue
        task_id = "amd_intro__" + _slug(source_dir.relative_to(root).as_posix())
        candidates.append(
            Candidate(
                suite="amd_intro",
                repo_url="https://github.com/Xilinx/Vitis-HLS-Introductory-Examples",
                commit=commit,
                license="Apache-2.0",
                source_root=root,
                source_dir=source_dir,
                task_id=task_id,
                top=top,
                kernel_sources=kernel_sources,
                tb_source=tb,
                headers=headers,
                data_files=_data_files(source_dir),
            )
        )
    return candidates


def _accel_candidates(root: Path) -> list[Candidate]:
    commit = _git(root, "rev-parse", "HEAD")
    candidates = []
    for source in sorted(root.rglob("*.cpp")):
        if source.name == "host.cpp":
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        signature = _extern_c_signature(text)
        if not signature:
            continue
        top, args = signature
        if _unsupported_accel_signature(args):
            continue
        source_dir = source.parent.parent if source.parent.name == "src" else source.parent
        headers = tuple(sorted(source.parent.glob("*.h"))) + tuple(
            sorted(source.parent.glob("*.hpp"))
        )
        task_id = "amd_accel__" + _slug(source.relative_to(root).with_suffix("").as_posix())
        candidates.append(
            Candidate(
                suite="amd_accel",
                repo_url="https://github.com/Xilinx/Vitis_Accel_Examples",
                commit=commit,
                license="MIT",
                source_root=root,
                source_dir=source_dir,
                task_id=task_id,
                top=top,
                kernel_sources=(source,),
                tb_source=None,
                headers=headers,
                data_files=(),
                generated_tb=True,
            )
        )
    return candidates


def _write_task(
    cand: Candidate,
    out_root: Path,
    source_hash: str,
    *,
    replace: bool,
    inject_tripcount_pragmas: bool,
) -> int:
    task_dir = out_root / cand.task_id
    if task_dir.exists():
        if not replace:
            raise FileExistsError(task_dir)
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)

    kernel_name = f"{cand.top}.cpp"
    tb_name = f"{cand.top}_tb.cpp"
    header_names = []
    for header in cand.headers:
        dest_name = header.name
        shutil.copy2(header, task_dir / dest_name)
        header_names.append(dest_name)
    for data in cand.data_files:
        shutil.copy2(data, task_dir / data.name)

    kernel_text, tripcount_count = _combined_kernel(
        cand, inject_tripcount_pragmas=inject_tripcount_pragmas
    )
    (task_dir / kernel_name).write_text(kernel_text, encoding="utf-8")
    if cand.tb_source is not None:
        shutil.copy2(cand.tb_source, task_dir / tb_name)
    else:
        (task_dir / tb_name).write_text(_generated_tb(cand), encoding="utf-8")

    (task_dir / "task.toml").write_text(
        _task_toml(
            cand,
            kernel_name,
            tb_name,
            header_names,
            source_hash,
            tripcount_count,
        ),
        encoding="utf-8",
    )
    (task_dir / "description.md").write_text(_description(cand, source_hash), encoding="utf-8")
    return tripcount_count


def _combined_kernel(
    cand: Candidate, *, inject_tripcount_pragmas: bool
) -> tuple[str, int]:
    chunks = [
        "/* Imported from a public HLS example. See task.toml [provenance]. */\n",
    ]
    tripcount_count = 0
    for source in cand.kernel_sources:
        chunks.append(f"\n/* BEGIN PUBLIC SOURCE: {source.name} */\n")
        source_text = source.read_text(encoding="utf-8", errors="replace")
        if inject_tripcount_pragmas:
            source_text, inserted = _add_tripcount_pragmas(source_text)
            tripcount_count += inserted
        chunks.append(source_text)
        chunks.append(f"\n/* END PUBLIC SOURCE: {source.name} */\n")
    return "".join(chunks), tripcount_count


def _add_tripcount_pragmas(
    source: str, *, max_tripcount: int = 4096
) -> tuple[str, int]:
    """Insert report-only tripcount pragmas before variable-bound loops."""

    output: list[str] = []
    inserted = 0
    previous_significant = ""
    for line in source.splitlines(keepends=True):
        if (
            _line_has_variable_bound_for(line)
            and "LOOP_TRIPCOUNT" not in previous_significant
        ):
            indent = re.match(r"\s*", line).group(0)
            output.append(
                f"{indent}#pragma HLS LOOP_TRIPCOUNT min=1 max={max_tripcount}"
                "\n"
            )
            inserted += 1
        output.append(line)
        stripped = line.strip()
        if stripped and not stripped.startswith("//"):
            previous_significant = stripped
    return "".join(output), inserted


def _line_has_variable_bound_for(line: str) -> bool:
    if line.lstrip().startswith("//"):
        return False
    match = re.search(r"\bfor\s*\(([^;]*);([^;]*);([^)]*)\)", line)
    if not match:
        return False
    condition = match.group(2)
    bound_match = re.search(r"[<>]=?\s*([A-Za-z_]\w*|[+-]?\d+)", condition)
    if not bound_match:
        return False
    return not re.fullmatch(r"[+-]?\d+", bound_match.group(1))


def _generated_tb(cand: Candidate) -> str:
    text = cand.kernel_sources[0].read_text(encoding="utf-8", errors="ignore")
    top, args = _extern_c_signature(text) or (cand.top, "")
    declarations, call_args = _tb_bindings(args)
    return f"""#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void {top}({args});

int main() {{
{declarations}
  {top}({call_args});
  std::cout << "PASS\\n";
  return 0;
}}
"""


def _tb_bindings(args: str) -> tuple[str, str]:
    declarations = []
    call_args = []
    for index, raw in enumerate(_split_args(args)):
        name = _arg_name(raw) or f"arg{index}"
        call_args.append(name)
        base = raw.replace("__restrict__", "").replace("restrict", "")
        if "*" in base or "&" in base:
            elem = base.split("*")[0].split("&")[0].replace("const", "").strip()
            elem = elem or "int"
            declarations.append(f"  static {elem} {name}_storage[64] = {{0}};")
            declarations.append(f"  {elem}* {name} = {name}_storage;")
        elif "int64_t" in base or "long" in base:
            declarations.append(f"  int64_t {name} = 16;")
        elif "char" in base:
            declarations.append(f"  char {name} = 1;")
        else:
            declarations.append(f"  int {name} = 16;")
    return "\n".join(declarations), ", ".join(call_args)


def _task_toml(
    cand: Candidate,
    kernel_name: str,
    tb_name: str,
    header_names: list[str],
    source_hash: str,
    tripcount_count: int,
) -> str:
    initial = (
        "Public AMD HLS example kernel. Preserve behavior while improving QoR "
        "with report-driven Vitis HLS pragmas."
    )
    source_url = f"{cand.repo_url}/tree/{cand.commit}/{cand.source_rel}"
    return f'''task_id = "{cand.task_id}"
task_type = "optimize"
difficulty = 3
top = "{cand.top}"
kernel_file = "{kernel_name}"
header_files = {json.dumps(header_names)}
public_tb = "{tb_name}"
budget = 60
initial_condition = "{initial}"

[target]
part = "{U55C_PART}"
clock_ns = {CLOCK_NS}

[provenance]
source = "{cand.suite}"
source_url = "{source_url}"
license = "{cand.license}"
top_function = "{cand.top}"
repo_commit = "{cand.commit}"
source_path = "{cand.source_rel}"
source_sha256 = "{source_hash}"
public_only = true
hidden_imported = false
reference_imported = false
generated_testbench = {str(cand.generated_tb).lower()}
tripcount_pragmas_inserted = {tripcount_count}
'''


def _description(cand: Candidate, source_hash: str) -> str:
    return f"""# {cand.task_id}

Optimize the public HLS top function `{cand.top}` imported from `{cand.source_rel}`.

Provenance:
- Source: {cand.repo_url}
- Commit: {cand.commit}
- License: {cand.license}
- Source SHA-256: {source_hash}
- Public-only import: no hidden, reference, or evaluator-only artifacts imported.
"""


def _manifest_record(
    cand: Candidate, source_hash: str, tripcount_count: int
) -> dict[str, object]:
    return {
        "task_id": cand.task_id,
        "source": cand.suite,
        "source_url": f"{cand.repo_url}/tree/{cand.commit}/{cand.source_rel}",
        "license": cand.license,
        "top_function": cand.top,
        "repo_commit": cand.commit,
        "source_path": cand.source_rel,
        "source_sha256": source_hash,
        "generated_testbench": cand.generated_tb,
        "tripcount_pragmas_inserted": tripcount_count,
    }


def _candidate_hash(cand: Candidate) -> str:
    digest = hashlib.sha256()
    for path in list(cand.kernel_sources) + list(cand.headers) + ([cand.tb_source] if cand.tb_source else []):
        if path is None:
            continue
        digest.update(path.relative_to(cand.source_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _existing_source_hashes(root: Path) -> set[str]:
    hashes = set()
    for toml in root.glob("*/task.toml"):
        text = toml.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r'(?m)^source_sha256\s*=\s*"([0-9a-f]{64})"', text)
        if match:
            hashes.add(match.group(1))
    return hashes


def _data_files(source_dir: Path) -> tuple[Path, ...]:
    return tuple(
        p
        for p in sorted(source_dir.iterdir())
        if p.is_file() and p.suffix.lower() in DATA_SUFFIXES
    )


def _top_from_tcl(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"(?m)^\s*set_top\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    return match.group(1) if match else ""


def _choose_tb(files: list[Path]) -> Path | None:
    tbs = [
        p
        for p in files
        if p.suffix.lower() in {".c", ".cc", ".cpp"}
        and re.search(r"(?:^|[_-])(tb|test)(?:[_\.-]|$)|(?:tb|test)\.", p.name, re.I)
    ]
    return sorted(tbs, key=lambda p: (0 if "tb" in p.name.lower() else 1, p.name))[0] if tbs else None


def _extern_c_signature(text: str) -> tuple[str, str] | None:
    match = re.search(
        r'extern\s+"C"\s*\{.*?\bvoid\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*\{',
        text,
        flags=re.S,
    )
    if not match:
        return None
    args = re.sub(r"\s+", " ", match.group(2)).strip()
    return match.group(1), args


def _unsupported_accel_signature(args: str) -> bool:
    lowered = args.lower()
    forbidden = ["hls::stream", "ap_axiu", "pkt", "v_dt", "class ", "std::"]
    if any(token in lowered for token in forbidden):
        return True
    return not _split_args(args)


def _split_args(args: str) -> list[str]:
    if not args or args.strip() == "void":
        return []
    result = []
    depth = 0
    start = 0
    for idx, ch in enumerate(args):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            result.append(args[start:idx].strip())
            start = idx + 1
    result.append(args[start:].strip())
    return [item for item in result if item]


def _arg_name(arg: str) -> str:
    cleaned = arg.replace("[", " [").strip()
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]*\])?$", cleaned)
    if not match:
        return ""
    return match.group(1)


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return re.sub(r"_+", "_", slug)


def _git(root: Path, *args: str) -> str:
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
