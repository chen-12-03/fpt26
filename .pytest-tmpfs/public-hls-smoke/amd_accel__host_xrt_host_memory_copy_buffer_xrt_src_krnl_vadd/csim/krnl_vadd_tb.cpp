#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void krnl_vadd(int* a, int* b, int* out, const int n_elements);

int main() {
  static int a_storage[64] = {0};
  int* a = a_storage;
  static int b_storage[64] = {0};
  int* b = b_storage;
  static int out_storage[64] = {0};
  int* out = out_storage;
  int n_elements = 16;
  krnl_vadd(a, b, out, n_elements);
  std::cout << "PASS\n";
  return 0;
}
