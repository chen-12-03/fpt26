#include <iostream>
#include "adder.h"

int main() {
    int a[10], b[10], c[10], z[10], expected[10];
    for (int i = 0; i < 10; ++i) {
        a[i] = i + 3;
        b[i] = (i + 1) * 2;
        c[i] = (i + 1) * 3;
        z[i] = 0x5a5a5a5a;
    }

    top(a, b, c, z);

    int mismatches = 0;
    for (int i = 0; i < 10; ++i) {
        expected[i] = a[i] + b[i] + c[i];
        if (z[i] != expected[i]) {
            std::cerr << "mismatch at " << i << ": got " << z[i]
                      << ", expected " << expected[i] << "\n";
            ++mismatches;
        }
    }
    return mismatches;
}
