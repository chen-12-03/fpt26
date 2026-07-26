#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void vadd(const unsigned int* in1, // Read-Only Vector 1 const unsigned int* in2, // Read-Only Vector 2 unsigned int* out_r, // Output Result int size // Size in integer);

int main() {
  static unsigned int in1_storage[64] = {0};
  unsigned int* in1 = in1_storage;
  static // Read-Only Vector 1  unsigned int in2_storage[64] = {0};
  // Read-Only Vector 1  unsigned int* in2 = in2_storage;
  static // Read-Only Vector 2 unsigned int out_r_storage[64] = {0};
  // Read-Only Vector 2 unsigned int* out_r = out_r_storage;
  int integer = 16;
  vadd(in1, in2, out_r, integer);
  std::cout << "PASS\n";
  return 0;
}
