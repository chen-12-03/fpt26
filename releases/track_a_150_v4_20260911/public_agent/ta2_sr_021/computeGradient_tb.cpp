#include <iostream>

#include "computeGradient.h"

static int run_case(int mode, FeatureType scale) {
    FeatureType grad[NUM_FEATURES];
    DataType feature[NUM_FEATURES];
    DataType before[NUM_FEATURES];

    for (int i = 0; i < NUM_FEATURES; ++i) {
        int value = mode == 0 ? (i % 23) - 11
                              : mode == 1 ? ((i & 1) ? -7 : 9)
                                          : ((i % 37) == 0 ? 31 : 0);
        feature[i] = DataType(value) / 16;
        before[i] = feature[i];
        grad[i] = FeatureType(127);
    }

    computeGradient(grad, feature, scale);
    for (int i = 0; i < NUM_FEATURES; ++i) {
        FeatureType expected = scale * feature[i];
        if (grad[i] != expected) {
            std::cerr << "gradient mismatch in public case " << mode
                      << " at " << i << std::endl;
            return 1;
        }
        if (feature[i] != before[i]) {
            std::cerr << "feature modified at " << i << std::endl;
            return 1;
        }
    }
    return 0;
}

int main() {
    if (run_case(0, FeatureType(1) / 2)) return 1;
    if (run_case(1, FeatureType(-5) / 4)) return 1;
    if (run_case(2, FeatureType(0))) return 1;
    std::cout << "PASS" << std::endl;
    return 0;
}
