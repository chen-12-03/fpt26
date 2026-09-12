
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

#include "trisolv.h"

void init_array(int n, double L[40][40], double x[40], double b[40]) {
    int i, j;

    for (i = 0; i < n; i++) {
        x[i] = -999;
        b[i] = (i) + (double)(((i * i + 3 * i) + 5) % 7) / 17.0;
        for (j = 0; j <= i; j++)
            L[i][j] = (double)(i + n - j + 1) * 2 / n;
    }
}

void print_array(int n, double x[40])

{
    int i;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "x");
    for (i = 0; i < n; i++) {
        fprintf(stderr, "%0.6lf ", x[i]);
        if (i % 20 == 0)
            fprintf(stderr, "\n");
    }
    fprintf(stderr, "\nend   dump: %s\n", "x");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;


    int n = 40;

    double L[40][40];
    double x[40];
    double b[40];

    init_array(n, L, x, b);

    kernel_trisolv(L, x, b);

    print_array(n, x);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}