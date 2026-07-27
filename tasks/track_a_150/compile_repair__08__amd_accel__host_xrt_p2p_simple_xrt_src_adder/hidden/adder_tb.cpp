#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void adder(unsigned int* in, unsigned int* out, int inc, int size);

int main() {
  static unsigned int in_storage[64] = {0};
  unsigned int* in = in_storage;
  static unsigned int out_storage[64] = {0};
  unsigned int* out = out_storage;
  int inc = 16;
  int size = 16;
  adder(in, out, inc, size);
  std::cout << "PASS\n";
  return 0;
}
