from tools.build_track_a_150 import _code_generation_stub


def test_generation_stub_preserves_direct_c_linkage() -> None:
    reference = """
#include "kernel.h"
extern "C" void kernel(int *out) {
    *out = 1;
}
"""

    stub = _code_generation_stub(reference, "kernel")

    assert 'extern "C" void kernel(int *out)' in stub
    assert "#error TRACK_A_CODE_GENERATION_REQUIRED" in stub
    assert "*out = 1" not in stub


def test_generation_stub_converts_c_linkage_block_to_exact_declaration() -> None:
    reference = """
#include "kernel.h"
extern "C" {
void kernel(int *out) {
    *out = 1;
}
}
"""

    stub = _code_generation_stub(reference, "kernel")

    assert 'extern "C" void kernel(int *out)' in stub
    assert stub.count('extern "C"') == 1


def test_generation_stub_keeps_cpp_linkage_when_reference_is_cpp() -> None:
    reference = """
#include "kernel.h"
void kernel(int *out) {
    *out = 1;
}
"""

    stub = _code_generation_stub(reference, "kernel")

    assert 'extern "C"' not in stub
    assert "void kernel(int *out)" in stub
