from __future__ import annotations

from tools.import_public_hls_tasks import _add_tripcount_pragmas


def test_importer_adds_tripcount_before_variable_bound_loops() -> None:
    source = """
void top(int *a, int n) {
  for (int i = 0; i < n; ++i) a[i] = i;
  for (int j = 0; j < 16; ++j) a[j] += 1;
}
""".lstrip()

    transformed, inserted = _add_tripcount_pragmas(source, max_tripcount=128)

    assert inserted == 1
    assert (
        "#pragma HLS LOOP_TRIPCOUNT min=1 max=128\n"
        "  for (int i = 0; i < n; ++i)"
    ) in transformed
    assert transformed.count("LOOP_TRIPCOUNT") == 1


def test_importer_does_not_duplicate_existing_tripcount() -> None:
    source = """
void top(int *a, int n) {
  #pragma HLS LOOP_TRIPCOUNT min=1 max=64
  for (int i = 0; i < n; ++i) {
    a[i] = i;
  }
}
""".lstrip()

    transformed, inserted = _add_tripcount_pragmas(source)

    assert inserted == 0
    assert transformed == source
