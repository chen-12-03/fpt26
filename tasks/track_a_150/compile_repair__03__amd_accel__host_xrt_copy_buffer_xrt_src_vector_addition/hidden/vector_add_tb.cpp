#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void vector_add(int* c, int* a, int* b, const int n_elements);

int main() {
  static int c_storage[64] = {0};
  int* c = c_storage;
  static int a_storage[64] = {0};
  int* a = a_storage;
  static int b_storage[64] = {0};
  int* b = b_storage;
  int n_elements = 16;
  vector_add(c, a, b, n_elements);
  std::cout << "PASS\n";
  return 0;
}
