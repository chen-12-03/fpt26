
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

#include "ludcmp.h"

void init_array(
    int n,
    double A[40][40],
    double b[40],
    double x[40],
    double y[40]) {
    int i, j;
    double fn = (double)n;

    for (i = 0; i < n; i++) {
        x[i] = 0;
        y[i] = 0;
        b[i] = ((i + 1) / fn / 2.0 + 4) + (double)(((i * i + 3 * i) + 7) % 11) / 13.0;
    }

    for (i = 0; i < n; i++) {
        for (j = 0; j <= i; j++)
            A[i][j] = (double)(-j % n) / n + 1;
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

void print_array(int n, double x[40])

{
    int i;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "x");
    for (i = 0; i < n; i++) {
        if (i % 20 == 0)
            fprintf(stderr, "\n");
        fprintf(stderr, "%0.6lf ", x[i]);
    }
    fprintf(stderr, "\nend   dump: %s\n", "x");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;


    int n = 40;

    double A[40][40];
    double b[40];
    double x[40];
    double y[40];

    init_array(n, A, b, x, y);

    kernel_ludcmp(A, b, x, y);

    print_array(n, x);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}