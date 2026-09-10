/*
 * Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
 * Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
#include "test.h"
#include <cstdio>

int main() {
    // Exercise every legal ROM address in a non-monotonic order and make
    // repeated calls visible to RTL CoSim.
    const int hidden_indices[] = {8, 1, 6, 3, 9, 0, 5, 2, 7, 4};
    int mismatches = 0;
    for (int index : hidden_indices) {
        const int actual = test(index);
        if (actual != 9) {
            std::fprintf(stderr, "hidden index %d: got %d, expected 9\n", index, actual);
            ++mismatches;
        }
    }
    return mismatches;
}
