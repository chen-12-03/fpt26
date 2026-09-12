
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

#include "syr2k.h"

void init_array(
    int n,
    int m,
    double *alpha,
    double *beta,
    double C[30][30],
    double A[30][20],
    double B[30][20]) {
    int i, j;

    *alpha = 1.5;
    *beta = 1.2;
    for (i = 0; i < n; i++)
        for (j = 0; j < m; j++) {
            A[i][j] = ((double)((i * j + 1) % n) / n) + (double)(((i * i + 3 * i) + (j * j + 3 * j) + 5) % 7) / 17.0;
            B[i][j] = (double)((i * j + 2) % m) / m;
        }
    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++) {
            C[i][j] = (double)((i * j + 3) % n) / m;
        }
}

void print_array(int n, double C[30][30]) {
    int i, j;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "C");
    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++) {
            if ((i * n + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", C[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "C");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;


    int n = 30;
    int m = 20;

    double alpha;
    double beta;
    double C[30][30];
    double A[30][20];
    double B[30][20];

    init_array(n, m, &alpha, &beta, C, A, B);

    kernel_syr2k(alpha, beta, C, A, B);

    print_array(n, C);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}