
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

#include "2mm.h"

void init_array(
    int ni,
    int nj,
    int nk,
    int nl,
    double *alpha,
    double *beta,
    double A[16][22],
    double B[22][18],
    double C[18][24],
    double D[16][24]) {
    int i, j;

    *alpha = 1.5;
    *beta = 1.2;
    for (i = 0; i < ni; i++)
        for (j = 0; j < nk; j++)
            A[i][j] = ((double)((i * j + 1) % ni) / ni) + (double)(((i * i + 3 * i) + (j * j + 3 * j) + 7) % 11) / 13.0;
    for (i = 0; i < nk; i++)
        for (j = 0; j < nj; j++)
            B[i][j] = (double)(i * (j + 1) % nj) / nj;
    for (i = 0; i < nj; i++)
        for (j = 0; j < nl; j++)
            C[i][j] = (double)((i * (j + 3) + 1) % nl) / nl;
    for (i = 0; i < ni; i++)
        for (j = 0; j < nl; j++)
            D[i][j] = (double)(i * (j + 2) % nk) / nk;
}

void print_array(int ni, int nl, double D[16][24]) {
    int i, j;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "D");
    for (i = 0; i < ni; i++)
        for (j = 0; j < nl; j++) {
            if ((i * ni + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", D[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "D");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;


    int ni = 16;
    int nj = 18;
    int nk = 22;
    int nl = 24;

    double alpha;
    double beta;
    double tmp[16][18];
    double A[16][22];
    double B[22][18];
    double C[18][24];
    double D[16][24];

    init_array(ni, nj, nk, nl, &alpha, &beta, A, B, C, D);

    kernel_2mm(alpha, beta, tmp, A, B, C, D);

    print_array(ni, nl, D);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}