
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

#include "mvt.h"

void init_array(
    int n,
    double x1[40],
    double x2[40],
    double y_1[40],
    double y_2[40],
    double A[40][40]) {
    int i, j;

    for (i = 0; i < n; i++) {
        x1[i] = ((double)(i % n) / n) + (double)(((i * i + 3 * i) + 5) % 7) / 17.0;
        x2[i] = (double)((i + 1) % n) / n;
        y_1[i] = (double)((i + 3) % n) / n;
        y_2[i] = (double)((i + 4) % n) / n;
        for (j = 0; j < n; j++)
            A[i][j] = (double)(i * j % n) / n;
    }
}

void print_array(int n, double x1[40], double x2[40])

{
    int i;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "x1");
    for (i = 0; i < n; i++) {
        if (i % 20 == 0)
            fprintf(stderr, "\n");
        fprintf(stderr, "%0.6lf ", x1[i]);
    }
    fprintf(stderr, "\nend   dump: %s\n", "x1");

    fprintf(stderr, "begin dump: %s", "x2");
    for (i = 0; i < n; i++) {
        if (i % 20 == 0)
            fprintf(stderr, "\n");
        fprintf(stderr, "%0.6lf ", x2[i]);
    }
    fprintf(stderr, "\nend   dump: %s\n", "x2");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;


    int n = 40;

    double A[40][40];
    double x1[40];
    double x2[40];
    double y_1[40];
    double y_2[40];

    init_array(n, x1, x2, y_1, y_2, A);

    kernel_mvt(x1, x2, y_1, y_2, A);

    print_array(n, x1, x2);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}