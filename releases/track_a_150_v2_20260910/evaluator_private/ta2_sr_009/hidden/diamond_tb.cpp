/*
 * Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
 * Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
#include "diamond.h"
#include <iostream>
#include <vector>

int main() {
    // A smaller legal multiple of 16 and a nonlinear value pattern make this
    // semantically distinct from the public boundary-size case.
    const int vector_count = 16;
    std::vector<vecOf16Words> input(vector_count);
    std::vector<vecOf16Words> output(vector_count);

    for (int i = 0; i < vector_count; ++i) {
        for (int lane = 0; lane < NUM_WORDS; ++lane) {
            input[i][lane] = static_cast<data_t>(
                (i * i * 37 + lane * 13 + 0x1234U) ^ (i << (lane & 3))
            );
            output[i][lane] = 0xa5a5a5a5U;
        }
    }

    diamond(input.data(), output.data(), vector_count);

    int mismatches = 0;
    for (int i = 0; i < vector_count; ++i) {
        for (int lane = 0; lane < NUM_WORDS; ++lane) {
            const data_t expected = input[i][lane] * 9U + 25U;
            if (output[i][lane] != expected) {
                if (mismatches < 4) {
                    std::cerr << "hidden mismatch at " << i << "," << lane
                              << ": got " << output[i][lane]
                              << ", expected " << expected << "\n";
                }
                ++mismatches;
            }
        }
    }
    return mismatches == 0 ? 0 : 1;
}
