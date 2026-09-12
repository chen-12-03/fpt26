
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

#include "float64_ge.h"
#include <iostream>
#include <vector>

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

    int fail = 0;

    // Define test cases
    struct {
        float64 a;
        float64 b;
        flag expected;
    } test_cases[] = {
        {0x5aULL, 0x3FF0000000000000ULL, 1}, // 2.0 >= 1.0
        {0x3FF0000000000000ULL, 0x4000000000000000ULL, 0}, // 1.0 >= 2.0
        {0xBFF0000000000000ULL, 0x3FF0000000000000ULL, 0}, // -1.0 >= 1.0
        {0x7FF8000000000000ULL, 0x3FF0000000000000ULL, 0}, // NaN >= 1.0
        {0x3FF0000000000000ULL, 0x3FF0000000000000ULL, 1}, // 1.0 >= 1.0
        {0x0000000000000000ULL, 0x8000000000000000ULL, 1}, // 0.0 >= -0.0
        {0x8000000000000000ULL, 0x0000000000000000ULL, 1}, // -0.0 >= 0.0
        {0xFFF0000000000000ULL, 0xFFF0000000000000ULL, 1}, // -inf >= -inf
        {0x7FF0000000000000ULL, 0x3FF0000000000000ULL, 1}, // +inf >= 1.0
        {0x3FF0000000000000ULL, 0x7FF0000000000000ULL, 0}, // 1.0 >= +inf
    };

    const int NUM_TESTS = sizeof(test_cases) / sizeof(test_cases[0]);

    for (int i = 0; i < NUM_TESTS; i++) {
        flag result = float64_ge(test_cases[i].a, test_cases[i].b);
        if (result != test_cases[i].expected) {
            printf(
                "Test case %d failed: float64_ge(%llx, %llx) = %d, expected "
                "%d\n",
                i,
                test_cases[i].a,
                test_cases[i].b,
                result,
                test_cases[i].expected);
            fail = 1;
        }
    }

    if (fail == 0) {
        printf("All test cases passed successfully.\n");
    }

    
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