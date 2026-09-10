
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

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "jacobi-1d.h"

void init_array(int n, double A[30], double B[30]) {
    int i;

    for (i = 0; i < n; i++) {
        A[i] = (((double)i + 2) / n) + (double)(((i * i + 3 * i) + 5) % 7) / 17.0;
        B[i] = ((double)i + 3) / n;
    }
}

void print_array(int n, double A[30])

{
    int i;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "A");
    for (i = 0; i < n; i++) {
        if (i % 20 == 0)
            fprintf(stderr, "\n");
        fprintf(stderr, "%0.6lf ", A[i]);
    }
    fprintf(stderr, "\nend   dump: %s\n", "A");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;


    int n = 30;
    int tsteps = 20;

    double A[30];
    double B[30];

    init_array(n, A, B);

    kernel_jacobi_1d(A, B);

    print_array(n, A);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}