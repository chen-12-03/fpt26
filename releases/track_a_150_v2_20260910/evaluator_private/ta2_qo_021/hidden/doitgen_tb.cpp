
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

#include "doitgen.h"

void init_array(
    int nr,
    int nq,
    int np,
    double A[10][8][12],
    double C4[12][12]) {
    int i, j, k;

    for (i = 0; i < nr; i++)
        for (j = 0; j < nq; j++)
            for (k = 0; k < np; k++)
                A[i][j][k] = ((double)((i * j + k) % np) / np) + (double)(((i * i + 3 * i) + (j * j + 3 * j) + (k * k + 3 * k) + 7) % 11) / 13.0;
    for (i = 0; i < np; i++)
        for (j = 0; j < np; j++)
            C4[i][j] = (double)(i * j % np) / np;
}

void print_array(int nr, int nq, int np, double A[10][8][12]) {
    int i, j, k;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "A");
    for (i = 0; i < nr; i++)
        for (j = 0; j < nq; j++)
            for (k = 0; k < np; k++) {
                if ((i * nq * np + j * np + k) % 20 == 0)
                    fprintf(stderr, "\n");
                fprintf(stderr, "%0.6lf ", A[i][j][k]);
            }
    fprintf(stderr, "\nend   dump: %s\n", "A");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;


    int nr = 10;
    int nq = 8;
    int np = 12;

    double A[10][8][12];
    double sum[12];
    double C4[12][12];

    init_array(nr, nq, np, A, C4);

    kernel_doitgen(A, C4, sum);

    print_array(nr, nq, np, A);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}