
#include <cstdio>

static int track_a_compare_file(const char *actual_name, const char *golden_name) {
    FILE *actual = std::fopen(actual_name, "rb");
    FILE *golden = std::fopen(golden_name, "rb");
    if (!actual || !golden) {
        if (actual) std::fclose(actual);
        if (golden) std::fclose(golden);
        return 1;
    }
    int different = 0;
    for (;;) {
        int left = std::fgetc(actual);
        int right = std::fgetc(golden);
        if (left != right) different = 1;
        if (left == EOF || right == EOF) {
            if (left != right) different = 1;
            break;
        }
    }
    std::fclose(actual);
    std::fclose(golden);
    return different;
}


#include <cstddef>
#include <cstdint>
#include <cstdio>

static unsigned long long track_a_hash_bytes(const void *address, std::size_t size) {
    const unsigned char *bytes = static_cast<const unsigned char *>(address);
    unsigned long long value = 1469598103934665603ULL;
    for (std::size_t index = 0; index < size; ++index) {
        value ^= bytes[index];
        value *= 1099511628211ULL;
    }
    return value;
}

#include <stdio.h>

#include "propagateFloat64NaN.h"

typedef unsigned long long bits64;
typedef unsigned long long float64;
typedef int flag;

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

    int result = 0;

    struct {
        float64 a;
        float64 b;
        float64 expected;
    } test_cases[] = {
        {0xFFF800000000005AULL,
         0x3FF0000000000000ULL,
         0xFFF800000000005AULL}, // Negative quiet NaN with payload, normal
        {0x7FF0000000000001ULL,
         0x3FF0000000000000ULL,
         0x7FF8000000000001ULL}, // Signaling NaN a
        {0x3FF0000000000000ULL,
         0x7FF0000000000001ULL,
         0x7FF8000000000001ULL}, // Signaling NaN b
        {0x7FF8000000000001ULL,
         0x7FF8000000000002ULL,
         0x7FF8000000000002ULL}, // Both quiet NaNs
        {0x7FF0000000000001ULL,
         0x7FF8000000000000ULL,
         0x7FF8000000000001ULL}, // Signaling a, quiet b
        {0x7FF8000000000000ULL,
         0x7FF0000000000001ULL,
         0x7FF8000000000001ULL}, // Quiet a, signaling b
        {0x7FF8000000000000ULL,
         0x7FF0000000000000ULL,
         0x7FF8000000000000ULL} // Quiet NaN vs Infinity

    };

    for (int i = 0; i < 7; ++i) {
        float64 output = propagateFloat64NaN(test_cases[i].a, test_cases[i].b);
        if (output != test_cases[i].expected) {
            printf(
                "Test case %d FAILED: input = (0x%016llX, 0x%016llX), expected "
                "= 0x%016llX, got = 0x%016llX\n",
                i,
                test_cases[i].a,
                test_cases[i].b,
                test_cases[i].expected,
                output);
            result = 1;
        }
    }

    if (result == 0)
        printf("All tests PASSED.\n");
    else
        printf("Some tests FAILED.\n");

    
    std::fprintf(stderr, "\nTRACK_A_OBSERVATION_BEGIN\n");
    std::fprintf(stderr, "TRACK_A_OBSERVATION_END\n");
    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}
