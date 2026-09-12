
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

#include "dfdiv.h"

double ullong_to_double(unsigned long long x) {
    union {
        double d;
        unsigned long long ll;
    } t;

    t.ll = x;
    return t.d;
}

const float64 a_input[22] = {
    0x7FFF000000000000ULL, 0x7FF0000000000000ULL, 0x7FF0000000000000ULL,
    0x7FF0000000000000ULL, 0x3FF0000000000000ULL, 0x3FF0000000000000ULL,
    0x0000000000000000ULL, 0x3FF0000000000000ULL, 0x0000000000000000ULL,
    0x8000000000000000ULL, 0x4008000000000000ULL, 0xC008000000000000ULL,
    0x4008000000000000ULL, 0xC008000000000000ULL, 0x4000000000000000ULL,
    0xC000000000000000ULL, 0x4000000000000000ULL, 0xC000000000000000ULL,
    0x3FF0000000000000ULL, 0xBFF0000000000000ULL, 0x3FF0000000000000ULL,
    0xBFF0000000000000ULL};

const float64 b_input[22] = {
    0x3FF0000000000000ULL, 0x7FF8000000000000ULL, 0x7FF0000000000000ULL,
    0x3FF0000000000000ULL, 0x7FF8000000000000ULL, 0x7FF0000000000000ULL,
    0x0000000000000000ULL, 0x0000000000000000ULL, 0x3FF0000000000000ULL,
    0x3FF0000000000000ULL, 0x4000000000000000ULL, 0x4000000000000000ULL,
    0xC000000000000000ULL, 0xC000000000000000ULL, 0x4010000000000000ULL,
    0x4010000000000000ULL, 0xC010000000000000ULL, 0xC010000000000000ULL,
    0x3FF8000000000000ULL, 0x3FF8000000000000ULL, 0xBFF8000000000000ULL,
    0xBFF8000000000000ULL};

const float64 z_output[22] = {
    0x7FFF000000000000ULL, 0x7FF8000000000000ULL, 0x7FFFFFFFFFFFFFFFULL,
    0x7FF0000000000000ULL, 0x7FF8000000000000ULL, 0x0000000000000000ULL,
    0x7FFFFFFFFFFFFFFFULL, 0x7FF0000000000000ULL, 0x0000000000000000ULL,
    0x8000000000000000ULL, 0x3FF8000000000000ULL, 0xBFF8000000000000ULL,
    0xBFF8000000000000ULL, 0x3FF8000000000000ULL, 0x3FE0000000000000ULL,
    0xBFE0000000000000ULL, 0xBFE0000000000000ULL, 0x3FE0000000000000ULL,
    0x3FE5555555555555ULL, 0xBFE5555555555555ULL, 0xBFE5555555555555ULL,
    0x3FE5555555555555ULL};

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

    int main_result;
    int i;
    float64 x1, x2;
    main_result = 0;
    for (i = 0; i < 22; i++) {
        float64 result;
        x1 = (a_input[i]) + 3;
        x2 = b_input[i];
        result = float64_div(x1, x2);
        main_result += (result != z_output[i]);

        printf(
            "a_input=%016llx b_input=%016llx expected=%016llx "
            "output=%016llx (%lf)\n",
            a_input[i],
            b_input[i],
            z_output[i],
            result,
            ullong_to_double(result));
    }
    printf("%d\n", main_result);
    
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