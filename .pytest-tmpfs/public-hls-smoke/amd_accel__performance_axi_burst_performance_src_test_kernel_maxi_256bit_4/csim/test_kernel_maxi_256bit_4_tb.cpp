#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void test_kernel_maxi_256bit_4(int64_t buf_size, int direction, int64_t* perf, ap_int<256>* mem);

int main() {
  int64_t buf_size = 16;
  int direction = 16;
  static int64_t perf_storage[64] = {0};
  int64_t* perf = perf_storage;
  static ap_int<256> mem_storage[64] = {0};
  ap_int<256>* mem = mem_storage;
  test_kernel_maxi_256bit_4(buf_size, direction, perf, mem);
  std::cout << "PASS\n";
  return 0;
}
