
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

#include "gemm.h"

void init_array(
    int ni,
    int nj,
    int nk,
    double *alpha,
    double *beta,
    double C[20][25],
    double A[20][30],
    double B[30][25]) {
    int i, j;

    *alpha = 1.5;
    *beta = 1.2;
    for (i = 0; i < ni; i++)
        for (j = 0; j < nj; j++)
            C[i][j] = ((double)((i * j + 1) % ni) / ni) + (double)(((i * i + 3 * i) + (j * j + 3 * j) + 7) % 11) / 13.0;
    for (i = 0; i < ni; i++)
        for (j = 0; j < nk; j++)
            A[i][j] = (double)(i * (j + 1) % nk) / nk;
    for (i = 0; i < nk; i++)
        for (j = 0; j < nj; j++)
            B[i][j] = (double)(i * (j + 2) % nj) / nj;
}

void print_array(int ni, int nj, double C[20][25]) {
    int i, j;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "C");
    for (i = 0; i < ni; i++)
        for (j = 0; j < nj; j++) {
            if ((i * ni + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", C[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "C");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;


    int ni = 20;
    int nj = 25;
    int nk = 30;

    double alpha;
    double beta;
    double C[20][25];
    double A[20][30];
    double B[30][25];

    init_array(ni, nj, nk, &alpha, &beta, C, A, B);

    kernel_gemm(alpha, beta, C, A, B);

    print_array(ni, nj, C);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}