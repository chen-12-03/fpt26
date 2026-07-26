from __future__ import annotations

from pathlib import Path

from tools.prepare_tripcount_patch_sample import prepare_samples


def test_prepare_tripcount_patch_sample_copies_public_files_only(tmp_path: Path) -> None:
    task_root = tmp_path / "tasks"
    task_dir = task_root / "generated" / "amd_accel__sample"
    task_dir.mkdir(parents=True)
    (task_dir / "hidden").mkdir()
    (task_dir / "reference").mkdir()
    (task_dir / "hidden" / "secret.cpp").write_text("secret", encoding="utf-8")
    (task_dir / "reference" / "gold.cpp").write_text("gold", encoding="utf-8")
    (task_dir / "task.toml").write_text(
        """
task_id = "amd_accel__sample"
top = "top"
kernel_file = "top.cpp"
header_files = []
public_tb = "top_tb.cpp"

[provenance]
source = "amd_accel"
source_path = "unit/sample"
source_sha256 = "abc"
""".lstrip(),
        encoding="utf-8",
    )
    (task_dir / "top.cpp").write_text(
        """
extern "C" void top(int *a, int n) {
  for (int i = 0; i < n; ++i) {
    a[i] = i;
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    (task_dir / "top_tb.cpp").write_text("int main(){return 0;}\n", encoding="utf-8")

    manifest = prepare_samples(
        task_root,
        tmp_path / "patched",
        ["amd_accel__sample"],
        max_tripcount=64,
    )

    patched = tmp_path / "patched" / "amd_accel__sample"
    assert not (patched / "hidden").exists()
    assert not (patched / "reference").exists()
    assert "#pragma HLS LOOP_TRIPCOUNT min=1 max=64" in (
        patched / "top.cpp"
    ).read_text(encoding="utf-8")
    assert manifest["imported"][0]["tripcount_pragmas_inserted"] == 1
