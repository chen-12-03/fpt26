#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void bandwidth(unsigned int* buffer0, unsigned int* buffer1);

int main() {
  static unsigned int buffer0_storage[64] = {0};
  unsigned int* buffer0 = buffer0_storage;
  static unsigned int buffer1_storage[64] = {0};
  unsigned int* buffer1 = buffer1_storage;
  bandwidth(buffer0, buffer1);
  std::cout << "PASS\n";
  return 0;
}
