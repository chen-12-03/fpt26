#include <iostream>

#include "dotProduct.h"

static int check(unsigned seed, int sparse_stride) {
    FeatureType param[NUM_FEATURES];
    DataType feature[NUM_FEATURES];
    FeatureType expected = 0;
    unsigned state = seed;

    for (int i = 0; i < NUM_FEATURES; ++i) {
        state = state * 1664525u + 1013904223u;
        int p = int((state >> 24) & 31u) - 16;
        state = state * 1664525u + 1013904223u;
        int f = int((state >> 25) & 15u) - 8;
        if (sparse_stride && i % sparse_stride != 0) p = 0;
        param[i] = FeatureType(p) / 8;
        feature[i] = DataType(f) / 16;
        FeatureType term = param[i] * feature[i];
        expected += term;
    }

    FeatureType actual = dotProduct(param, feature);
    if (actual != expected) {
        std::cerr << "hidden dotProduct mismatch seed=" << seed
                  << " stride=" << sparse_stride << std::endl;
        return 1;
    }
    return 0;
}

int main() {
    const unsigned seeds[] = {1u, 0x12345678u, 0xdeadbeefu, 0x9e3779b9u};
    const int strides[] = {0, 3, 17, 31};
    for (int i = 0; i < 4; ++i) {
        if (check(seeds[i], strides[i])) return 1;
    }
    std::cout << "PASS" << std::endl;
    return 0;
}
