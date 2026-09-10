/*
 * Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
 * Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
#include "test.h"
#include <cstdio>

int main() {
    const int public_indices[] = {0, 5, 9};
    int mismatches = 0;
    for (int index : public_indices) {
        const int actual = test(index);
        if (actual != 9) {
            std::fprintf(stderr, "index %d: got %d, expected 9\n", index, actual);
            ++mismatches;
        }
    }
    return mismatches;
}
