
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

#include "lu.h"

void init_array(int n, double A[40][40]) {
    int i, j;

    for (i = 0; i < n; i++) {
        for (j = 0; j <= i; j++)
            A[i][j] = ((double)(-j % n) / n + 1) + (double)(((i * i + 3 * i) + (j * j + 3 * j) + 5) % 7) / 17.0;
        for (j = i + 1; j < n; j++) {
            A[i][j] = 0;
        }
        A[i][i] = 1;
    }

    int r, s, t;
    double B[40][40];
    for (r = 0; r < n; ++r)
        for (s = 0; s < n; ++s)
            B[r][s] = 0;
    for (t = 0; t < n; ++t)
        for (r = 0; r < n; ++r)
            for (s = 0; s < n; ++s)
                B[r][s] += A[r][t] * A[s][t];
    for (r = 0; r < n; ++r)
        for (s = 0; s < n; ++s)
            A[r][s] = B[r][s];
}

void print_array(int n, double A[40][40])

{
    int i, j;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "A");
    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++) {
            if ((i * n + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", A[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "A");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;


    int n = 40;

    double A[40][40];

    init_array(n, A);

    kernel_lu(A);

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