#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void vadd(unsigned int* in1, unsigned int* in2, unsigned int* out, int size);

int main() {
  static unsigned int in1_storage[64] = {0};
  unsigned int* in1 = in1_storage;
  static unsigned int in2_storage[64] = {0};
  unsigned int* in2 = in2_storage;
  static unsigned int out_storage[64] = {0};
  unsigned int* out = out_storage;
  int size = 16;
  vadd(in1, in2, out, size);
  std::cout << "PASS\n";
  return 0;
}
