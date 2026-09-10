
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

#include "gemver.h"

void init_array(
    int n,
    double *alpha,
    double *beta,
    double A[40][40],
    double u1[40],
    double v1[40],
    double u2[40],
    double v2[40],
    double w[40],
    double x[40],
    double y[40],
    double z[40]) {
    int i, j;

    *alpha = 1.5;
    *beta = 1.2;

    double fn = (double)n;

    for (i = 0; i < n; i++) {
        u1[i] = (i) + (double)(((i * i + 3 * i) + 5) % 7) / 17.0;
        u2[i] = ((i + 1) / fn) / 2.0;
        v1[i] = ((i + 1) / fn) / 4.0;
        v2[i] = ((i + 1) / fn) / 6.0;
        y[i] = ((i + 1) / fn) / 8.0;
        z[i] = ((i + 1) / fn) / 9.0;
        x[i] = 0.0;
        w[i] = 0.0;
        for (j = 0; j < n; j++)
            A[i][j] = (double)(i * j % n) / n;
    }
}

void print_array(int n, double w[40]) {
    int i;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "w");
    for (i = 0; i < n; i++) {
        if (i % 20 == 0)
            fprintf(stderr, "\n");
        fprintf(stderr, "%0.6lf ", w[i]);
    }
    fprintf(stderr, "\nend   dump: %s\n", "w");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;


    int n = 40;

    double alpha;
    double beta;
    double A[40][40];
    double u1[40];
    double v1[40];
    double u2[40];
    double v2[40];
    double w[40];
    double x[40];
    double y[40];
    double z[40];

    init_array(n, &alpha, &beta, A, u1, v1, u2, v2, w, x, y, z);

    kernel_gemver(alpha, beta, A, u1, v1, u2, v2, w, x, y, z);

    print_array(n, w);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}