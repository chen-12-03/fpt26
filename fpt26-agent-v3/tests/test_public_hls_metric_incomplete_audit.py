from __future__ import annotations

import json
from pathlib import Path

from tools.audit_public_hls_metric_incomplete import audit


def test_metric_incomplete_audit_classifies_by_source_signals(
    tmp_path: Path,
) -> None:
    task_root = tmp_path / "tasks"
    variable = task_root / "public__variable"
    stream = task_root / "public__stream"
    perf = task_root / "public__perf"
    for task_dir in (variable, stream, perf):
        task_dir.mkdir(parents=True)

    (variable / "kernel.cpp").write_text(
        "void top(int *in, int *out, int size) {\n"
        "  for (int i = 0; i < size; ++i) out[i] = in[i];\n"
        "}\n",
        encoding="utf-8",
    )
    (stream / "kernel.cpp").write_text(
        "#include <hls_stream.h>\n"
        "void top(hls::stream<int> &in, hls::stream<int> &out) {\n"
        "#pragma HLS DATAFLOW\n"
        "  int v = in.read(); out.write(v);\n"
        "}\n",
        encoding="utf-8",
    )
    (perf / "kernel.cpp").write_text(
        "void top(long buf_size, long *perf, int *mem) {\n"
        "  for (long i = 0; i < buf_size; ++i) perf[0] += mem[i];\n"
        "}\n",
        encoding="utf-8",
    )

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "scoreable_gate": {
                    "metric_incomplete_task_ids": [
                        "public__variable",
                        "public__stream",
                        "public__perf",
                    ]
                },
                "validated": [
                    {
                        "task_id": "public__variable",
                        "source": "public",
                        "source_path": "memory/simple",
                        "top_function": "top",
                    },
                    {
                        "task_id": "public__stream",
                        "source": "public",
                        "source_path": "interface/stream",
                        "top_function": "top",
                    },
                    {
                        "task_id": "public__perf",
                        "source": "public",
                        "source_path": "performance/burst",
                        "top_function": "top",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    smoke = tmp_path / "smoke.json"
    smoke.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "task_id": task_id,
                        "csim_ok": True,
                        "synth_ok": True,
                        "latency_worst": None,
                        "interval_max": None,
                    }
                    for task_id in (
                        "public__variable",
                        "public__stream",
                        "public__perf",
                    )
                ]
            }
        ),
        encoding="utf-8",
    )

    report = audit(manifest_path=manifest, smoke_path=smoke, task_root=task_root)
    by_task = {record["task_id"]: record for record in report["records"]}

    assert (
        by_task["public__variable"]["resolution_class"]
        == "bounded_wrapper_small_sample_candidate"
    )
    assert (
        by_task["public__stream"]["resolution_class"]
        == "quarantine_protocol_or_dataflow_modeling_required"
    )
    assert (
        by_task["public__perf"]["resolution_class"]
        == "quarantine_low_value_performance_counter_kernel"
    )
    assert report["scope"]["api_or_vitis_run"] is False
