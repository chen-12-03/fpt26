#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void vadd(unsigned int* in1, unsigned int* in2, unsigned int* out, int size);

int main() {
    const int size = 37;
    unsigned int in1[64] = {};
    unsigned int in2[64] = {};
    unsigned int out[64] = {};
    for (int i = 0; i < size; ++i) {
        in1[i] = 17u * i + 3u;
        in2[i] = 11u * i * i + 5u;
    }
    vadd(in1, in2, out, size);
    for (int i = 0; i < size; ++i) {
        if (out[i] != in1[i] + in2[i]) {
            std::cerr << "FAIL at " << i << std::endl;
            return 1;
        }
    }
    return 0;
}
