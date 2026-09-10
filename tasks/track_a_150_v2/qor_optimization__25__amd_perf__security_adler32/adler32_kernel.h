#ifndef TRACK_A_AMD_PERF_ADLER32_KERNEL_H
#define TRACK_A_AMD_PERF_ADLER32_KERNEL_H

void adler32_kernel(
    const unsigned char data[256],
    unsigned length,
    unsigned* checksum);

#endif
