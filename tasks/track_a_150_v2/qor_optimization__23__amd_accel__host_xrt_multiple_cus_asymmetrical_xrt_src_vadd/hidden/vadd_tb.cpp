#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void vadd(unsigned int* in1, unsigned int* in2, unsigned int* out, int size);

int main() {
    const int size = 53;
    unsigned int in1[64] = {};
    unsigned int in2[64] = {};
    unsigned int out[64] = {};
    for (int i = 0; i < size; ++i) {
        in1[i] = 29u * i + 7u;
        in2[i] = 13u * i * i + 19u;
    }
    vadd(in1, in2, out, size);
    for (int i = 0; i < size; ++i) {
        if (out[i] != in1[i] + in2[i]) {
            std::cerr << "FAIL: hidden vector add mismatch" << std::endl;
            return 1;
        }
    }
    return 0;
}
