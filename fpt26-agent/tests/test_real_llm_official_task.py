from __future__ import annotations

import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from agent.main import EXIT_LLM_ERROR, EXIT_SAFE_FALLBACK, EXIT_SUCCESS, main


REQUIRED_LLM_ENV = [
    "FPT26_LLM_BASE_URL",
    "FPT26_LLM_MODEL",
    "FPT26_LLM_TIMEOUT_SECONDS",
    "FPT26_LLM_MAX_OUTPUT_TOKENS",
    "FPT26_LLM_TEMPERATURE",
    "FPT26_LLM_LICENSE",
    "FPT26_LLM_SOURCE",
]


@unittest.skipUnless(
    os.environ.get("FPT26_RUN_HLS_TESTS") == "1"
    and os.environ.get("FPT26_RUN_LLM_TESTS") == "1"
    and os.environ.get("FPT26_RUN_REAL_API_TESTS") == "1",
    "set FPT26_RUN_HLS_TESTS=1, FPT26_RUN_LLM_TESTS=1 and FPT26_RUN_REAL_API_TESTS=1 to run the real API smoke test",
)
class RealLLMOfficialTaskSmokeTests(unittest.TestCase):
    def test_projection_bugfix_real_api_single_repair_attempt(self):
        missing = [name for name in REQUIRED_LLM_ENV if not os.environ.get(name)]
        if missing:
            self.skipTest("missing real LLM config: " + ", ".join(missing))

        stdout = io.StringIO()
        stderr = io.StringIO()
        output_root = Path("fpt26-agent/runs/real_llm_official_task")
        env_overrides = {
            "FPT26_LLM_MAX_RETRIES": "0",
        }
        with mock.patch.dict(os.environ, env_overrides, clear=False):
            code = main(
                [
                    "--task",
                    "fpt26-harness/tasks/projection_bugfix",
                    "--mode",
                    "repair",
                    "--output-root",
                    str(output_root),
                    "--max-repair-attempts",
                    "1",
                ],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertNotIn(os.environ.get("FPT26_LLM_API_KEY", "__no_key__"), stdout.getvalue())
        self.assertNotIn(os.environ.get("FPT26_LLM_API_KEY", "__no_key__"), stderr.getvalue())
        self.assertTrue(stdout.getvalue().strip(), stderr.getvalue())
        summary = json.loads(stdout.getvalue())
        run_dir = Path(summary["run_directory"])
        manifest_text = (run_dir / "run_manifest.json").read_text(encoding="utf-8")
        self.assertNotIn(os.environ.get("FPT26_LLM_API_KEY", "__no_key__"), manifest_text)
        self.assertEqual(summary["task_id"], "projection_bugfix")
        self.assertEqual(summary["stage_statuses"][0]["stage"], "csim")
        self.assertEqual(summary["stage_statuses"][0]["status"], "runtime_fail")
        self.assertLessEqual(summary["llm_usage"].get("attempt_count") or 0, 1)
        self.assertTrue((run_dir / "candidates" / "c000_baseline" / "kernel.cpp").is_file())

        if summary["repair_status"] == "repaired":
            self.assertEqual(code, EXIT_SUCCESS)
            self.assertEqual(summary["selected_candidate_id"], "c001_repair_llm_01")
            self.assertEqual([item["status"] for item in summary["stage_statuses"]], ["runtime_fail", "pass", "pass"])
            self.assertEqual(
                (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8"),
                (run_dir / "candidates" / "c001_repair_llm_01" / "kernel.cpp").read_text(encoding="utf-8"),
            )
        else:
            self.assertIn(code, {EXIT_SAFE_FALLBACK, EXIT_LLM_ERROR})
            if code == EXIT_SAFE_FALLBACK:
                self.assertTrue(summary["model_repair_failed"])
            self.assertEqual(
                (run_dir / "final" / "kernel.cpp").read_text(encoding="utf-8"),
                (run_dir / "candidates" / "c000_baseline" / "kernel.cpp").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
