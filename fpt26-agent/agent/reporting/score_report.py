from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

from llm4hls.scoring import grade


Scorer = Callable[[Any, str, Path], Any]


def run_official_scoring(
    task: Any,
    final_kernel: str,
    run_directory: str | Path,
    *,
    scorer: Scorer = grade,
) -> dict[str, Any]:
    run_dir = Path(run_directory)
    score_dir = run_dir / "scoring"
    score_dir.mkdir(parents=True, exist_ok=False)
    scorecard = scorer(task, final_kernel, score_dir / "official_grade")
    rendered = scorecard.render() if hasattr(scorecard, "render") else str(scorecard)
    data = scorecard_to_dict(scorecard)
    data["rendered"] = rendered
    data["paths"] = {
        "score_dir": str(score_dir),
        "scorecard_json": str(score_dir / "scorecard.json"),
        "scorecard_txt": str(score_dir / "scorecard.txt"),
        "official_grade_root": str(score_dir / "official_grade"),
    }
    (score_dir / "scorecard.txt").write_text(rendered + "\n", encoding="utf-8")
    (score_dir / "scorecard.json").write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return data


def scorecard_to_dict(scorecard: Any) -> dict[str, Any]:
    if is_dataclass(scorecard):
        return _json_value(asdict(scorecard))
    if hasattr(scorecard, "to_dict"):
        value = scorecard.to_dict()
        if isinstance(value, dict):
            return _json_value(value)
    if isinstance(scorecard, dict):
        return _json_value(scorecard)
    result: dict[str, Any] = {}
    for key in (
        "task_id",
        "difficulty",
        "functional_pass",
        "synth_pass",
        "cosim_pass",
        "baseline_latency",
        "candidate_latency",
        "acceleration",
        "is_opt",
        "score",
    ):
        if hasattr(scorecard, key):
            result[key] = _json_value(getattr(scorecard, key))
    return result


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
