
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

#include <iostream>
#include "dot_product.h"

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

    int A[SIZE], B[SIZE];
    int expected = 0;

    // Initialize arrays with sample values
    for (int i = 0; i < SIZE; i++) {
        A[i] = (i) + 3;
        B[i] = SIZE - i;
        expected += A[i] * B[i];
    }

    int result = dot_product(A, B);

    std::cout << "Result: " << result << std::endl;
    std::cout << "Expected: " << expected << std::endl;

    if (result == expected) {
        std::cout << "Test PASSED" << std::endl;
        return 0;
    } else {
        std::cout << "Test FAILED" << std::endl;
        return 1;
    }

    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}

