import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.ir import SCHEMA_VERSION, load_ir
from agent.llm_client import LLMCallResult, LLMTimeoutError
from agent.spec_extractor import (
    SpecExtractionJSONError,
    SpecExtractionLLMError,
    SpecExtractionValidationError,
    extract_spec_to_ir,
)


def valid_natural_language_ir() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": "vector_add",
        "input_mode": "natural_language",
        "top_function": "vector_add",
        "source_file": None,
        "testbench_file": None,
        "inputs": [
            {"name": "a", "data_type": "int", "shape": [16]},
            {"name": "b", "data_type": "int", "shape": [16]},
        ],
        "outputs": [
            {"name": "c", "data_type": "int", "shape": [16]},
        ],
        "clock_period_ns": 10.0,
        "hls_part": "xcu55c-fsvh2892-2L-e",
        "verification": {
            "csim": {"enabled": True},
            "synth": {"enabled": True},
            "cosim": {"enabled": False},
        },
        "inferred_fields": {
            "source_file": {"reason": "pending deterministic template generation"},
            "testbench_file": {"reason": "pending deterministic template generation"},
        },
    }


def llm_result(response_text: str, *, usage: bool = True) -> LLMCallResult:
    return LLMCallResult(
        model="open-source-model",
        response_text=response_text,
        input_tokens=17 if usage else None,
        output_tokens=19 if usage else None,
        total_tokens=36 if usage else None,
        elapsed_seconds=0.25,
        prompt_hash="a" * 64,
    )


class SpecExtractorTests(unittest.TestCase):
    def output_dir(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_valid_json_response_writes_ir_and_metadata(self):
        output_dir = self.output_dir()
        response_text = json.dumps(valid_natural_language_ir())

        with mock.patch("agent.spec_extractor.call_chat_completion", return_value=llm_result(response_text)):
            result = extract_spec_to_ir("Add two int arrays of length 16.", output_dir)

        saved_ir = load_ir(output_dir / "ir.json")
        metadata = json.loads((output_dir / "llm_call.json").read_text(encoding="utf-8"))

        self.assertEqual(result.ir_path, output_dir / "ir.json")
        self.assertEqual(result.metadata_path, output_dir / "llm_call.json")
        self.assertEqual(saved_ir.task_id, "vector_add")
        self.assertEqual(saved_ir.input_mode, "natural_language")
        self.assertEqual(metadata["model"], "open-source-model")
        self.assertEqual(metadata["prompt_hash"], "a" * 64)
        self.assertEqual(metadata["input_tokens"], 17)
        self.assertEqual(metadata["output_tokens"], 19)
        self.assertEqual(metadata["total_tokens"], 36)
        self.assertEqual(metadata["elapsed_seconds"], 0.25)
        self.assertNotIn("api", json.dumps(metadata).lower())
        self.assertNotIn("secret", json.dumps(metadata).lower())

    def test_json_markdown_code_block_is_accepted(self):
        output_dir = self.output_dir()
        response_text = "```json\n" + json.dumps(valid_natural_language_ir(), indent=2) + "\n```"

        with mock.patch("agent.spec_extractor.call_chat_completion", return_value=llm_result(response_text)):
            extract_spec_to_ir("Vector add.", output_dir)

        saved_ir = load_ir(output_dir / "ir.json")

        self.assertEqual(saved_ir.top_function, "vector_add")

    def test_invalid_json_fails_without_writing_ir(self):
        output_dir = self.output_dir()

        with mock.patch("agent.spec_extractor.call_chat_completion", return_value=llm_result("```json\nnot json\n```")):
            with self.assertRaises(SpecExtractionJSONError):
                extract_spec_to_ir("Vector add.", output_dir)

        self.assertFalse((output_dir / "ir.json").exists())
        self.assertFalse((output_dir / "llm_call.json").exists())

    def test_ir_validation_failure_is_clear(self):
        output_dir = self.output_dir()
        data = valid_natural_language_ir()
        data["clock_period_ns"] = -1

        with mock.patch("agent.spec_extractor.call_chat_completion", return_value=llm_result(json.dumps(data))):
            with self.assertRaises(SpecExtractionValidationError) as ctx:
                extract_spec_to_ir("Vector add.", output_dir)

        self.assertIn("clock_period_ns must be a positive number", str(ctx.exception))
        self.assertFalse((output_dir / "ir.json").exists())

    def test_llm_call_failure_is_clear(self):
        output_dir = self.output_dir()

        with mock.patch(
            "agent.spec_extractor.call_chat_completion",
            side_effect=LLMTimeoutError("LLM request timed out after 1 seconds"),
        ):
            with self.assertRaises(SpecExtractionLLMError) as ctx:
                extract_spec_to_ir("Vector add.", output_dir)

        self.assertIn("LLM call failed", str(ctx.exception))
        self.assertFalse((output_dir / "ir.json").exists())

    def test_missing_token_usage_is_saved_as_null(self):
        output_dir = self.output_dir()
        response_text = json.dumps(valid_natural_language_ir())

        with mock.patch("agent.spec_extractor.call_chat_completion", return_value=llm_result(response_text, usage=False)):
            extract_spec_to_ir("Vector add.", output_dir)

        metadata = json.loads((output_dir / "llm_call.json").read_text(encoding="utf-8"))

        self.assertIsNone(metadata["input_tokens"])
        self.assertIsNone(metadata["output_tokens"])
        self.assertIsNone(metadata["total_tokens"])


if __name__ == "__main__":
    unittest.main()
