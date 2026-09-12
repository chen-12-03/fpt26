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
    const unsigned length = 193u;
    for (unsigned i = 0; i < length; ++i) {
        data[i] = static_cast<unsigned char>((i * 73u + 19u) & 0xffu);
    }
    const unsigned expected = software_adler32(data, length);
    unsigned actual = 0u;
    adler32_kernel(data, length, &actual);
    if (actual != expected) {
        std::fprintf(stderr, "FAIL: got %08x expected %08x\n", actual, expected);
        return 1;
    }
    std::puts("PASS");
    return 0;
}
