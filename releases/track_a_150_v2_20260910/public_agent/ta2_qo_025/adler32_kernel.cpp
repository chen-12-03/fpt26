/*
 * Adapted from the AMD Vitis Security Library Adler-32 example.
 * Copyright (C) 2026, Advanced Micro Devices, Inc.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "adler32_kernel.h"

void adler32_kernel(
    const unsigned char data[256],
    unsigned length,
    unsigned* checksum) {
#pragma HLS INTERFACE m_axi port=data offset=slave bundle=gmem depth=256
#pragma HLS INTERFACE m_axi port=checksum offset=slave bundle=gmem depth=1
#pragma HLS INTERFACE s_axilite port=data bundle=control
#pragma HLS INTERFACE s_axilite port=length bundle=control
#pragma HLS INTERFACE s_axilite port=checksum bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control

    const unsigned base = 65521u;
    unsigned s1 = 1u;
    unsigned s2 = 0u;

    for (unsigned i = 0; i < 256u; ++i) {
#pragma HLS PIPELINE II=1
        if (i < length) {
            s1 += data[i];
            if (s1 >= base) s1 -= base;
            s2 += s1;
            if (s2 >= base) s2 -= base;
        }
    }
    *checksum = (s2 << 16) | s1;
}
