#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void krnl_vmul(int* a, int* b, int* c, const int length_r);

int main() {
  static int a_storage[64] = {0};
  int* a = a_storage;
  static int b_storage[64] = {0};
  int* b = b_storage;
  static int c_storage[64] = {0};
  int* c = c_storage;
  int length_r = 16;
  krnl_vmul(a, b, c, length_r);
  std::cout << "PASS\n";
  return 0;
}
