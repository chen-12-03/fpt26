
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

#include "countLeadingZeros32.h"
#include <iostream>

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

    int test_result = 0;

    // Test cases
    bits32 test_inputs[] = {
        0x5a,
        0x7FFFFFFF,
        0xFFFFFFFF,
        0x00000001,
        0x00000000,
        0x10000000,
        0x08000000,
        0x00008000,
        0x00000080,
        0x00000002,
    };
    int8 expected_outputs[] = {
        0,
        1,
        0,
        31,
        32,
        3,
        4,
        16,
        24,
        30,
    };
    int num_tests = sizeof(test_inputs) / sizeof(test_inputs[0]);

    // Run tests
    for (int i = 0; i < num_tests; ++i) {
        int8 actual_output = countLeadingZeros32(test_inputs[i]);
        if (actual_output != expected_outputs[i]) {
            std::cout << "Test case " << i << " failed:" << std::endl;
            std::cout << "  Input: 0x" << std::hex << test_inputs[i]
                      << std::endl;
            std::cout << "  Expected output: " << std::dec
                      << (int)expected_outputs[i] << std::endl;
            std::cout << "  Actual output: " << std::dec << (int)actual_output
                      << std::endl;
            test_result = 1; // Set error flag
        } else {
            std::cout << "Test case " << i << " passed." << std::endl;
        }
    }

    if (test_result == 0) {
        std::cout << "All tests passed!" << std::endl;
    } else {
        std::cout << "Some tests failed." << std::endl;
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