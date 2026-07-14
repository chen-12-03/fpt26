import json
import tempfile
import unittest
from pathlib import Path

from agent.ir import HLSIRValidationError, SCHEMA_VERSION, load_ir


def valid_ir() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": "vector_add",
        "input_mode": "existing_code",
        "top_function": "vector_add",
        "source_file": "benchmarks/public/vector_add/kernel.cpp",
        "testbench_file": "benchmarks/public/vector_add/host.cpp",
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
        "inferred_fields": {},
    }


class HLSIRTests(unittest.TestCase):
    def write_ir(self, data: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ir.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_valid_ir_loads_and_saves(self):
        input_path = self.write_ir(valid_ir())

        ir = load_ir(input_path)

        self.assertEqual(ir.schema_version, SCHEMA_VERSION)
        self.assertEqual(ir.task_id, "vector_add")
        self.assertEqual(ir.input_mode, "existing_code")
        self.assertEqual(ir.top_function, "vector_add")
        self.assertEqual(ir.clock_period_ns, 10.0)

        output_path = input_path.with_name("saved_ir.json")
        ir.save(output_path)
        reloaded = load_ir(output_path)

        self.assertEqual(reloaded.to_dict(), ir.to_dict())

    def test_missing_required_field_fails_with_clear_error(self):
        data = valid_ir()
        del data["top_function"]

        with self.assertRaises(HLSIRValidationError) as ctx:
            load_ir(self.write_ir(data))

        self.assertIn("missing required field(s): top_function", str(ctx.exception))

    def test_invalid_clock_period_fails(self):
        data = valid_ir()
        data["clock_period_ns"] = 0

        with self.assertRaises(HLSIRValidationError) as ctx:
            load_ir(self.write_ir(data))

        self.assertIn("clock_period_ns must be a positive number", str(ctx.exception))

    def test_existing_code_requires_source_and_testbench_fields(self):
        data = valid_ir()
        del data["source_file"]
        del data["testbench_file"]

        with self.assertRaises(HLSIRValidationError) as ctx:
            load_ir(self.write_ir(data))

        message = str(ctx.exception)
        self.assertIn("missing required field(s): source_file, testbench_file", message)
        self.assertIn("source_file is required when input_mode is 'existing_code'", message)
        self.assertIn("testbench_file is required when input_mode is 'existing_code'", message)

    def test_natural_language_allows_unmaterialized_source_paths(self):
        data = valid_ir()
        data["input_mode"] = "natural_language"
        data["source_file"] = None
        data["testbench_file"] = None
        data["inferred_fields"] = {
            "source_file": {"status": "pending_template_generation"},
            "testbench_file": {"status": "pending_template_generation"},
        }

        ir = load_ir(self.write_ir(data))

        self.assertIsNone(ir.source_file)
        self.assertIsNone(ir.testbench_file)


if __name__ == "__main__":
    unittest.main()
