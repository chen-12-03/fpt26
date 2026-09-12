#include <iostream>
#include "adder.h"

int main() {
    int a[10], b[10], c[10], z[10], expected[10];
    for (int i = 0; i < 10; ++i) {
        a[i] = (i * i + 17) * (i & 1 ? -1 : 1);
        b[i] = 3 * i - 11;
        c[i] = 29 - 5 * i;
        z[i] = 0x3c3c3c3c;
    }

    top(a, b, c, z);

    int mismatches = 0;
    for (int i = 0; i < 10; ++i) {
        expected[i] = a[i] + b[i] + c[i];
        if (z[i] != expected[i]) {
            std::cerr << "hidden mismatch at " << i << ": got " << z[i]
                      << ", expected " << expected[i] << "\n";
            ++mismatches;
        }
    }
    return mismatches;
}
