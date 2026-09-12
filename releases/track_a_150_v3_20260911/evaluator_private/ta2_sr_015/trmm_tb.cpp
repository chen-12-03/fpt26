
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

#include "trmm.h"

void init_array(
    int m,
    int n,
    double *alpha,
    double A[20][20],
    double B[20][30]) {
    int i, j;

    *alpha = 1.5;
    for (i = 0; i < m; i++) {
        for (j = 0; j < i; j++) {
            A[i][j] = ((double)((i + j) % m) / m) + (double)(((i * i + 3 * i) + (j * j + 3 * j) + 5) % 7) / 17.0;
        }
        A[i][i] = 1.0;
        for (j = 0; j < n; j++) {
            B[i][j] = (double)((n + (i - j)) % n) / n;
        }
    }
}

void print_array(int m, int n, double B[20][30]) {
    int i, j;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "B");
    for (i = 0; i < m; i++)
        for (j = 0; j < n; j++) {
            if ((i * m + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", B[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "B");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;


    int m = 20;
    int n = 30;

    double alpha;
    double A[20][20];
    double B[20][30];

    init_array(m, n, &alpha, A, B);

    kernel_trmm(alpha, A, B);

    print_array(m, n, B);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}