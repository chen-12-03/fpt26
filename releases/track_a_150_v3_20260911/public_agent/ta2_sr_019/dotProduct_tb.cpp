#include <iostream>

#include "dotProduct.h"

static int run_case(int mode) {
    FeatureType param[NUM_FEATURES];
    FeatureType param_before[NUM_FEATURES];
    DataType feature[NUM_FEATURES];
    DataType feature_before[NUM_FEATURES];
    FeatureType expected = 0;

    for (int i = 0; i < NUM_FEATURES; ++i) {
        int p = mode == 0 ? (i % 17) - 8
                          : mode == 1 ? ((i % 29) == 0 ? 24 : 0)
                                      : ((i & 1) ? -3 : 5);
        int f = mode == 0 ? (i % 13) - 6
                          : mode == 1 ? ((i % 7) - 3)
                                      : ((i % 11) - 5);
        param[i] = FeatureType(p) / 16;
        feature[i] = DataType(f) / 16;
        param_before[i] = param[i];
        feature_before[i] = feature[i];
        FeatureType term = param[i] * feature[i];
        expected += term;
    }

    FeatureType actual = dotProduct(param, feature);
    if (actual != expected) {
        std::cerr << "dotProduct mismatch in public case " << mode << std::endl;
        return 1;
    }
    for (int i = 0; i < NUM_FEATURES; ++i) {
        if (param[i] != param_before[i] || feature[i] != feature_before[i]) {
            std::cerr << "dotProduct modified an input at " << i << std::endl;
            return 1;
        }
    }
    return 0;
}

int main() {
    for (int mode = 0; mode < 3; ++mode) {
        if (run_case(mode)) return 1;
    }
    std::cout << "PASS" << std::endl;
    return 0;
}
