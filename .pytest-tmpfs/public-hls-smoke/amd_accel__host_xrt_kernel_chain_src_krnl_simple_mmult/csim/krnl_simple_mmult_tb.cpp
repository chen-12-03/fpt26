#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void krnl_simple_mmult(int* a, int* b, int* c, int* d, int* output, int dim);

int main() {
  static int a_storage[64] = {0};
  int* a = a_storage;
  static int b_storage[64] = {0};
  int* b = b_storage;
  static int c_storage[64] = {0};
  int* c = c_storage;
  static int d_storage[64] = {0};
  int* d = d_storage;
  static int output_storage[64] = {0};
  int* output = output_storage;
  int dim = 16;
  krnl_simple_mmult(a, b, c, d, output, dim);
  std::cout << "PASS\n";
  return 0;
}
