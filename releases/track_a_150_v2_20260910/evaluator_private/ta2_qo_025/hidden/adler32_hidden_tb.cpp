#include "adler32_kernel.h"

#include <cstdio>

static unsigned software_adler32(const unsigned char* data, unsigned length) {
    const unsigned base = 65521u;
    unsigned s1 = 1u;
    unsigned s2 = 0u;
    for (unsigned i = 0; i < length; ++i) {
        s1 = (s1 + data[i]) % base;
        s2 = (s2 + s1) % base;
    }
    return (s2 << 16) | s1;
}

int main() {
    unsigned char data[256] = {};
    const unsigned length = 251u;
    unsigned state = 0x9e3779b9u;
    for (unsigned i = 0; i < length; ++i) {
        state = state * 1664525u + 1013904223u;
        data[i] = static_cast<unsigned char>(state >> 24);
    }
    const unsigned expected = software_adler32(data, length);
    unsigned actual = 0u;
    adler32_kernel(data, length, &actual);
    if (actual != expected) {
        std::fprintf(stderr, "FAIL: hidden vector mismatch\n");
        return 1;
    }
    return 0;
}
