#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void copy_kernel(int* a, int* b, const int n_elements, const int direction);

int main() {
  static int a_storage[64] = {0};
  int* a = a_storage;
  static int b_storage[64] = {0};
  int* b = b_storage;
  int n_elements = 16;
  int direction = 16;
  copy_kernel(a, b, n_elements, direction);
  std::cout << "PASS\n";
  return 0;
}
