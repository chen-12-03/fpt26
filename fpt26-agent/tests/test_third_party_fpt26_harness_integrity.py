import hashlib
import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
THIRD_PARTY_ROOT = REPO_ROOT / "third_party"
HARNESS_ROOT = THIRD_PARTY_ROOT / "fpt26_harness"
UPSTREAM_JSON = THIRD_PARTY_ROOT / "fpt26_harness.upstream.json"
SHA256_MANIFEST = THIRD_PARTY_ROOT / "fpt26_harness.sha256"

REQUIRED_PATHS = [
    "llm4hls/harness.py",
    "llm4hls/tools.py",
    "llm4hls/task.py",
    "llm4hls/vitis.py",
    "llm4hls/scoring.py",
    "scripts/run_poc.py",
    "tasks",
]

BANNED_DIR_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".autopilot",
    "runs",
    "logs",
    "hls_prj",
    "project",
    "project_csim",
    "csim_proj",
    "synth_proj",
    "cosim_proj",
}
BANNED_FILE_SUFFIXES = (
    ".log",
    ".jou",
    ".str",
    ".wdb",
    ".vcd",
    ".vpd",
    ".pyc",
    ".pyo",
)
SHA_LINE_RE = re.compile(r"^[0-9a-f]{64}  .+$")


def _relative_files() -> list[str]:
    return sorted(
        path.relative_to(HARNESS_ROOT).as_posix()
        for path in HARNESS_ROOT.rglob("*")
        if path.is_file()
    )


def _read_manifest() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, line in enumerate(SHA256_MANIFEST.read_text(encoding="utf-8").splitlines(), start=1):
        if not SHA_LINE_RE.fullmatch(line):
            raise AssertionError(f"invalid SHA manifest line {line_number}: {line!r}")
        digest, rel_path = line.split("  ", 1)
        if rel_path in entries:
            raise AssertionError(f"duplicate SHA manifest path: {rel_path}")
        entries[rel_path] = digest
    return entries


def _assert_legal_relative_path(testcase: unittest.TestCase, rel_path: str) -> None:
    path = Path(rel_path)
    testcase.assertFalse(path.is_absolute(), rel_path)
    testcase.assertNotIn("\\", rel_path)
    testcase.assertNotIn("//", rel_path)
    testcase.assertNotEqual(rel_path, "")
    testcase.assertNotIn("..", path.parts)
    testcase.assertFalse(rel_path.startswith("./"), rel_path)
    testcase.assertFalse(rel_path.endswith("/"), rel_path)


def _assert_not_generated_artifact(testcase: unittest.TestCase, rel_path: str) -> None:
    parts = set(Path(rel_path).parts)
    testcase.assertTrue(parts.isdisjoint(BANNED_DIR_PARTS), rel_path)
    testcase.assertFalse(rel_path.endswith(BANNED_FILE_SUFFIXES), rel_path)
    testcase.assertFalse(rel_path.endswith(":Zone.Identifier"), rel_path)


class ThirdPartyFpt26HarnessIntegrityTests(unittest.TestCase):
    def test_required_files_are_present(self):
        self.assertTrue(HARNESS_ROOT.is_dir(), HARNESS_ROOT)
        for rel_path in REQUIRED_PATHS:
            with self.subTest(path=rel_path):
                self.assertTrue((HARNESS_ROOT / rel_path).exists(), rel_path)

    def test_upstream_json_is_parseable_and_consistent(self):
        data = json.loads(UPSTREAM_JSON.read_text(encoding="utf-8"))

        self.assertEqual(data["frozen_path"], "third_party/fpt26_harness")
        self.assertEqual(data["sha256_manifest_path"], "third_party/fpt26_harness.sha256")
        self.assertIsNone(data["git_repository"])
        self.assertIsNone(data["git_revision"])
        self.assertEqual(data["file_count"], len(_relative_files()))

    def test_sha_manifest_paths_are_unique_sorted_and_legal(self):
        lines = SHA256_MANIFEST.read_text(encoding="utf-8").splitlines()
        paths = [line.split("  ", 1)[1] for line in lines]

        self.assertEqual(paths, sorted(paths))
        self.assertEqual(len(paths), len(set(paths)))
        for rel_path in paths:
            with self.subTest(path=rel_path):
                _assert_legal_relative_path(self, rel_path)
                _assert_not_generated_artifact(self, rel_path)

    def test_each_manifest_hash_matches_file(self):
        entries = _read_manifest()
        for rel_path, expected_digest in entries.items():
            with self.subTest(path=rel_path):
                payload = (HARNESS_ROOT / rel_path).read_bytes()
                actual_digest = hashlib.sha256(payload).hexdigest()
                self.assertEqual(actual_digest, expected_digest)

    def test_no_unrecorded_files_exist(self):
        entries = _read_manifest()
        self.assertEqual(set(entries), set(_relative_files()))

    def test_no_cache_or_run_artifacts_are_frozen(self):
        for rel_path in _relative_files():
            with self.subTest(path=rel_path):
                _assert_not_generated_artifact(self, rel_path)


if __name__ == "__main__":
    unittest.main()
