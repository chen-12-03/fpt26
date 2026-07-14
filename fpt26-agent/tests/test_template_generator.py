import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.ir import SCHEMA_VERSION
from agent.template_generator import TemplateGenerationError, generate_vector_add_template


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
            "operation": {"value": "vector_add", "source": "test"},
            "source_file": {"reason": "pending deterministic template generation"},
            "testbench_file": {"reason": "pending deterministic template generation"},
        },
    }


class TemplateGeneratorTests(unittest.TestCase):
    def make_tmpdir(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def write_ir(self, data: dict, directory: Path) -> Path:
        path = directory / "ir.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_generates_stable_vector_add_kernel_and_host(self):
        tmp = self.make_tmpdir()
        ir_path = self.write_ir(valid_natural_language_ir(), tmp)
        out_dir = tmp / "generated"

        result = generate_vector_add_template(ir_path, out_dir)

        kernel = result.kernel_path.read_text(encoding="utf-8")
        host = result.host_path.read_text(encoding="utf-8")

        self.assertEqual(result.top_function, "vector_add")
        self.assertEqual(
            result.function_signature,
            'extern "C" void vector_add(const int a[VECTOR_ADD_SIZE], const int b[VECTOR_ADD_SIZE], int c[VECTOR_ADD_SIZE])',
        )
        self.assertIn("static const int VECTOR_ADD_SIZE = 16;", kernel)
        self.assertIn("extern \"C\" void vector_add", kernel)
        self.assertIn("c[i] = a[i] + b[i];", kernel)
        self.assertIn("expected_output[i] = a_data[i] + b_data[i];", host)
        self.assertIn("return 1;", host)
        self.assertIn("return 0;", host)

    def test_generated_code_compiles_and_runs_with_gxx(self):
        tmp = self.make_tmpdir()
        ir_path = self.write_ir(valid_natural_language_ir(), tmp)
        out_dir = tmp / "generated"

        generate_vector_add_template(ir_path, out_dir)
        executable = tmp / "vector_add_test"

        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                str(out_dir / "kernel.cpp"),
                str(out_dir / "host.cpp"),
                "-o",
                str(executable),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(compile_result.returncode, 0, compile_result.stderr)

        run_result = subprocess.run(
            [str(executable)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(run_result.returncode, 0, run_result.stderr)
        self.assertIn("vector_add passed: 16 elements checked", run_result.stdout)

    def test_refuses_to_overwrite_existing_outputs_by_default(self):
        tmp = self.make_tmpdir()
        ir_path = self.write_ir(valid_natural_language_ir(), tmp)
        out_dir = tmp / "generated"

        generate_vector_add_template(ir_path, out_dir)

        with self.assertRaises(TemplateGenerationError) as ctx:
            generate_vector_add_template(ir_path, out_dir)

        self.assertIn("refusing to overwrite", str(ctx.exception))

    def test_allows_overwrite_when_explicit(self):
        tmp = self.make_tmpdir()
        ir_path = self.write_ir(valid_natural_language_ir(), tmp)
        out_dir = tmp / "generated"

        generate_vector_add_template(ir_path, out_dir)
        (out_dir / "kernel.cpp").write_text("stale\n", encoding="utf-8")
        generate_vector_add_template(ir_path, out_dir, overwrite=True)

        self.assertIn("extern \"C\" void vector_add", (out_dir / "kernel.cpp").read_text(encoding="utf-8"))

    def test_unsupported_operation_fails(self):
        tmp = self.make_tmpdir()
        data = valid_natural_language_ir()
        data["inferred_fields"]["operation"]["value"] = "matmul"
        ir_path = self.write_ir(data, tmp)

        with self.assertRaises(TemplateGenerationError) as ctx:
            generate_vector_add_template(ir_path, tmp / "generated")

        self.assertIn("unsupported operation", str(ctx.exception))

    def test_shape_mismatch_fails(self):
        tmp = self.make_tmpdir()
        data = valid_natural_language_ir()
        data["outputs"][0]["shape"] = [8]
        ir_path = self.write_ir(data, tmp)

        with self.assertRaises(TemplateGenerationError) as ctx:
            generate_vector_add_template(ir_path, tmp / "generated")

        self.assertIn("shapes must match", str(ctx.exception))

    def test_unsupported_data_type_fails(self):
        tmp = self.make_tmpdir()
        data = valid_natural_language_ir()
        data["inputs"][0]["data_type"] = "float"
        ir_path = self.write_ir(data, tmp)

        with self.assertRaises(TemplateGenerationError) as ctx:
            generate_vector_add_template(ir_path, tmp / "generated")

        self.assertIn("unsupported data type", str(ctx.exception))

    def test_existing_code_ir_is_rejected(self):
        tmp = self.make_tmpdir()
        data = valid_natural_language_ir()
        data["input_mode"] = "existing_code"
        data["source_file"] = "benchmarks/public/vector_add/kernel.cpp"
        data["testbench_file"] = "benchmarks/public/vector_add/host.cpp"
        ir_path = self.write_ir(data, tmp)

        with self.assertRaises(TemplateGenerationError) as ctx:
            generate_vector_add_template(ir_path, tmp / "generated")

        self.assertIn("requires input_mode 'natural_language'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
