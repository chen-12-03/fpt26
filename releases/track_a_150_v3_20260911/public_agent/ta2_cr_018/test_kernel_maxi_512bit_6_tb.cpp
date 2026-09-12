#include <ap_int.h>
#include <cstdint>
#include <cstdio>

extern "C" void test_kernel_maxi_512bit_6(int64_t buf_size, int direction, int64_t* perf, ap_int<512>* mem);

int main() {
    const int64_t buf_size = 4096;
    int64_t perf[4] = {-1, -1, -1, -1};
    ap_int<512> mem[64] = {};
    test_kernel_maxi_512bit_6(buf_size, 0, perf, mem);
    int errors = 0;
    for (int i = 0; i < 64; ++i)
        errors += (mem[i] != i);
    errors += (perf[1] != 0 || perf[2] != 32 || perf[3] != 32);
    if (errors)
        std::fprintf(stderr, "FAIL: write path errors=%d\n", errors);
    return errors ? 1 : 0;
}
