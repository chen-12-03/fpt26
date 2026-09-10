#include <stdio.h>

#include "add128.h"

typedef struct {
    bits64 a0;
    bits64 a1;
    bits64 b0;
    bits64 b1;
    bits64 expected_z0;
    bits64 expected_z1;
} TestCase;

int main() {
    const bits64 inputs[][4] = {
        {0xFEDCBA9876543210ULL, 0x0123456789ABCDEFULL,
         0x123456789ABCDEF0ULL, 0x0FEDCBA987654321ULL},
        {0x8000000000000000ULL, 0x7FFFFFFFFFFFFFFFULL,
         0x8000000000000000ULL, 0x0000000000000001ULL},
        {0xDEADBEEF01234567ULL, 0xCAFEBABE76543210ULL,
         0x13579BDF2468ACE0ULL, 0x1020304050607080ULL},
    };
    for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); ++i) {
        bits64 z0 = 0, z1 = 0;
        add128(inputs[i][0], inputs[i][1], inputs[i][2], inputs[i][3], &z0, &z1);
        unsigned __int128 a = (static_cast<unsigned __int128>(inputs[i][0]) << 64) | inputs[i][1];
        unsigned __int128 b = (static_cast<unsigned __int128>(inputs[i][2]) << 64) | inputs[i][3];
        unsigned __int128 expected = a + b;
        if (z0 != static_cast<bits64>(expected >> 64) ||
            z1 != static_cast<bits64>(expected)) return 1;
    }
    return 0;
}
