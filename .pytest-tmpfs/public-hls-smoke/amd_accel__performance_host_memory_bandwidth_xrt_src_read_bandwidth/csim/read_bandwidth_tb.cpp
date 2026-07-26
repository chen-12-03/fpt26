#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void read_bandwidth(TYPE* input0, int64_t buf_size, int64_t iter);

int main() {
  static TYPE input0_storage[64] = {0};
  TYPE* input0 = input0_storage;
  int64_t buf_size = 16;
  int64_t iter = 16;
  read_bandwidth(input0, buf_size, iter);
  std::cout << "PASS\n";
  return 0;
}
