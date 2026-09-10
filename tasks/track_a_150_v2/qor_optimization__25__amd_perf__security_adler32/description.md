# Track-A v2: qor_optimization

Improve latency/throughput and area without changing functionality.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `valid_baseline`.

## Kernel specification

# Adler-32 checksum kernel

Implement the Adler-32 checksum over a bounded byte buffer. The top-level
function is `adler32_kernel` with the complete signature
`void adler32_kernel(const unsigned char data[256], unsigned length, unsigned* checksum)`.
`data` contains up to 256 input bytes, `length` selects the valid prefix, and
`checksum` receives the result. Inputs with `0 <= length <= 256` must be
supported.

Initialize `s1` to 1 and `s2` to 0. For each valid byte, add the byte to `s1`
modulo 65521, then add the new `s1` to `s2` modulo 65521. Return the packed
32-bit value `(s2 << 16) | s1`. Preserve the declared pointer/array interface
and synthesize for the configured Alveo U55C target.

This package adapts the algorithm and test intent of AMD's Vitis Security
Library Adler-32 example into a bounded, standalone HLS task. Public and hidden
testbenches use different deterministic input sequences and independently
compute the expected checksum.
