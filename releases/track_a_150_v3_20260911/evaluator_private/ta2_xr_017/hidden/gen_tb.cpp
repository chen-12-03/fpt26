
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

#include <cstdio>

#include "mul64To128.h"

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

    int result = 0;

    struct {
        bits64 a;
        bits64 b;
        bits64 expected_high;
        bits64 expected_low;
    } test_cases[] = {
        {0x5aULL,
         0x0000000100000000ULL,
         0x0000000000000001ULL,
         0x0000000000000000ULL},
        {0xFFFFFFFFFFFFFFFFULL,
         0xFFFFFFFFFFFFFFFFULL,
         0xFFFFFFFFFFFFFFFEULL,
         0x0000000000000001ULL},
        {0x123456789ABCDEF0ULL,
         0x0FEDCBA987654321ULL,
         0x0121FA00AD77D742ULL,
         0x2236D88FE5618CF0ULL},
        {0x0000000000000000ULL,
         0xFFFFFFFFFFFFFFFFULL,
         0x0000000000000000ULL,
         0x0000000000000000ULL},
        {0xFFFFFFFFFFFFFFFFULL,
         0x0000000000000001ULL,
         0x0000000000000000ULL,
         0xFFFFFFFFFFFFFFFFULL},
    };

    for (int i = 0; i < 5; ++i) {
        bits64 high, low;
        mul64To128(test_cases[i].a, test_cases[i].b, &high, &low);
        if (high != test_cases[i].expected_high ||
            low != test_cases[i].expected_low) {
            printf(
                "Test case %d FAILED: a = 0x%016llX, b = 0x%016llX, expected = "
                "(0x%016llX, 0x%016llX), got = (0x%016llX, 0x%016llX)\n",
                i,
                test_cases[i].a,
                test_cases[i].b,
                test_cases[i].expected_high,
                test_cases[i].expected_low,
                high,
                low);
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