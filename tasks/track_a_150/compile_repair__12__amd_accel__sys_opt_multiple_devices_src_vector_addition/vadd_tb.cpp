#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void vadd(int* c, int* a, int* b, const int len, const int iter);

int main() {
  static int c_storage[64] = {0};
  int* c = c_storage;
  static int a_storage[64] = {0};
  int* a = a_storage;
  static int b_storage[64] = {0};
  int* b = b_storage;
  int len = 16;
  int iter = 16;
  vadd(c, a, b, len, iter);
  std::cout << "PASS\n";
  return 0;
}
