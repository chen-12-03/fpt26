#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void dummy_kernel(unsigned int* buffer0, unsigned int* buffer1, unsigned int size);

int main() {
  static unsigned int buffer0_storage[64] = {0};
  unsigned int* buffer0 = buffer0_storage;
  static unsigned int buffer1_storage[64] = {0};
  unsigned int* buffer1 = buffer1_storage;
  int size = 16;
  dummy_kernel(buffer0, buffer1, size);
  std::cout << "PASS\n";
  return 0;
}
