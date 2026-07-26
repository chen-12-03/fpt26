#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void write_bandwidth(TYPE* output0, int64_t buf_size, int64_t iter);

int main() {
  static TYPE output0_storage[64] = {0};
  TYPE* output0 = output0_storage;
  int64_t buf_size = 16;
  int64_t iter = 16;
  write_bandwidth(output0, buf_size, iter);
  std::cout << "PASS\n";
  return 0;
}
