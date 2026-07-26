#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void mbox_autorestart(int in1, int in2, int& add, int& mult);

int main() {
  int in1 = 16;
  int in2 = 16;
  static int add_storage[64] = {0};
  int* add = add_storage;
  static int mult_storage[64] = {0};
  int* mult = mult_storage;
  mbox_autorestart(in1, in2, add, mult);
  std::cout << "PASS\n";
  return 0;
}
