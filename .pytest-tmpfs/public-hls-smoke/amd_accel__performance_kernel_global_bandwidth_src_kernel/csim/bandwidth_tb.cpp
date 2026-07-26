#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void bandwidth(TYPE* __restrict__ input0, TYPE* __restrict__ output0, #if NDDR_BANKS == 3 TYPE* __restrict__ output1, #elif NDDR_BANKS > 3 TYPE* __restrict__ input1, TYPE* __restrict__ output1, #endif int64_t num_blocks);

int main() {
  static TYPE input0_storage[64] = {0};
  TYPE* input0 = input0_storage;
  static TYPE output0_storage[64] = {0};
  TYPE* output0 = output0_storage;
  static #if NDDR_BANKS == 3 TYPE output1_storage[64] = {0};
  #if NDDR_BANKS == 3 TYPE* output1 = output1_storage;
  static #elif NDDR_BANKS > 3 TYPE input1_storage[64] = {0};
  #elif NDDR_BANKS > 3 TYPE* input1 = input1_storage;
  static TYPE output1_storage[64] = {0};
  TYPE* output1 = output1_storage;
  int64_t num_blocks = 16;
  bandwidth(input0, output0, output1, input1, output1, num_blocks);
  std::cout << "PASS\n";
  return 0;
}
