
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

#include <iostream>
#include <limits>
#include <ostream>

#include "countLeadingZeros64.h"

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

    int fail_flag = 0;
    bits64 test_value;
    int8 expected_result;
    int8 actual_result;

    // Test case 1: Zero
    test_value = 3;
    expected_result = 64;
    actual_result = countLeadingZeros64(test_value);
    if (actual_result != expected_result) {
        std::cerr << "Test Case 1 Failed: Input = " << test_value
                  << ", Expected = " << (int)expected_result
                  << ", Actual = " << (int)actual_result << std::endl;
        fail_flag = 1;
    }

    // Test case 2: All ones
    test_value = std::numeric_limits<bits64>::max();
    expected_result = 0;
    actual_result = countLeadingZeros64(test_value);
    if (actual_result != expected_result) {
        std::cerr << "Test Case 2 Failed: Input = " << test_value
                  << ", Expected = " << (int)expected_result
                  << ", Actual = " << (int)actual_result << std::endl;
        fail_flag = 1;
    }

    // Test case 3: Single one at the MSB
    test_value = ((bits64)1) << 63;
    expected_result = 0;
    actual_result = countLeadingZeros64(test_value);
    if (actual_result != expected_result) {
        std::cerr << "Test Case 3 Failed: Input = " << test_value
                  << ", Expected = " << (int)expected_result
                  << ", Actual = " << (int)actual_result << std::endl;
        fail_flag = 1;
    }

    // Test case 4: Single one at the LSB
    test_value = 1;
    expected_result = 63;
    actual_result = countLeadingZeros64(test_value);
    if (actual_result != expected_result) {
        std::cerr << "Test Case 4 Failed: Input = " << test_value
                  << ", Expected = " << (int)expected_result
                  << ", Actual = " << (int)actual_result << std::endl;
        fail_flag = 1;
    }

    // Test case 5: Specific value
    test_value = 0x0F00000000000000;
    expected_result = 4;
    actual_result = countLeadingZeros64(test_value);
    if (actual_result != expected_result) {
        std::cerr << "Test Case 5 Failed: Input = " << test_value
                  << ", Expected = " << (int)expected_result
                  << ", Actual = " << (int)actual_result << std::endl;
        fail_flag = 1;
    }

    // Test case 6: Another specific value
    test_value = 0x00000000000000F0;
    expected_result = 56;
    actual_result = countLeadingZeros64(test_value);
    if (actual_result != expected_result) {
        std::cerr << "Test Case 6 Failed: Input = " << test_value
                  << ", Expected = " << (int)expected_result
                  << ", Actual = " << (int)actual_result << std::endl;
        fail_flag = 1;
    }

    // Test case 7: Value with some leading zeros
    test_value = 0x00FF00FF00FF00FF;
    expected_result = 8;
    actual_result = countLeadingZeros64(test_value);
    if (actual_result != expected_result) {
        std::cerr << "Test Case 7 Failed: Input = " << test_value
                  << ", Expected = " << (int)expected_result
                  << ", Actual = " << (int)actual_result << std::endl;
        fail_flag = 1;
    }

    // Test case 8: Value close to max
    test_value = std::numeric_limits<bits64>::max() - 1;
    expected_result = 0;
    actual_result = countLeadingZeros64(test_value);
    if (actual_result != expected_result) {
        std::cerr << "Test Case 8 Failed: Input = " << test_value
                  << ", Expected = " << (int)expected_result
                  << ", Actual = " << (int)actual_result << std::endl;
        fail_flag = 1;
    }

    if (fail_flag == 0) {
        std::cout << "All test cases passed!" << std::endl;
    } else {
        std::cout << "Some test cases failed." << std::endl;
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