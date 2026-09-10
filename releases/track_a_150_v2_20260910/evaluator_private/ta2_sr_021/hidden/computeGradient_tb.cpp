#include <iostream>

#include "computeGradient.h"

static int check(unsigned seed, FeatureType scale) {
    FeatureType grad[NUM_FEATURES];
    DataType feature[NUM_FEATURES];
    unsigned state = seed;

    for (int i = 0; i < NUM_FEATURES; ++i) {
        state = state * 1103515245u + 12345u;
        int value = int((state >> 24) & 31u) - 16;
        feature[i] = DataType(value) / 8;
        grad[i] = FeatureType(-255);
    }

    computeGradient(grad, feature, scale);
    for (int i = 0; i < NUM_FEATURES; ++i) {
        FeatureType expected = scale * feature[i];
        if (grad[i] != expected) {
            std::cerr << "hidden gradient mismatch seed=" << seed
                      << " at " << i << std::endl;
            return 1;
        }
    }
    return 0;
}

int main() {
    const unsigned seeds[] = {7u, 0x10203040u, 0xabcdef01u, 0x31415926u};
    const FeatureType scales[] = {
        FeatureType(3) / 8,
        FeatureType(-7) / 4,
        FeatureType(15) / 16,
        FeatureType(-1) / 32,
    };
    for (int i = 0; i < 4; ++i) {
        if (check(seeds[i], scales[i])) return 1;
    }
    std::cout << "PASS" << std::endl;
    return 0;
}
