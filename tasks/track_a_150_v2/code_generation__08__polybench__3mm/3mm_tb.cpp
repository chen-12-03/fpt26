
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

#include "3mm.h"

void init_array(
    int ni,
    int nj,
    int nk,
    int nl,
    int nm,
    double A[16][20],
    double B[20][18],
    double C[18][24],
    double D[24][22]) {
    int i, j;

    for (i = 0; i < ni; i++)
        for (j = 0; j < nk; j++)
            A[i][j] = ((double)((i * j + 1) % ni) / (5 * ni)) + (double)(((i * i + 3 * i) + (j * j + 3 * j) + 5) % 7) / 17.0;
    for (i = 0; i < nk; i++)
        for (j = 0; j < nj; j++)
            B[i][j] = (double)((i * (j + 1) + 2) % nj) / (5 * nj);
    for (i = 0; i < nj; i++)
        for (j = 0; j < nm; j++)
            C[i][j] = (double)(i * (j + 3) % nl) / (5 * nl);
    for (i = 0; i < nm; i++)
        for (j = 0; j < nl; j++)
            D[i][j] = (double)((i * (j + 2) + 2) % nk) / (5 * nk);
}

void print_array(int ni, int nl, double G[16][22]) {
    int i, j;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "G");
    for (i = 0; i < ni; i++)
        for (j = 0; j < nl; j++) {
            if ((i * ni + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", G[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "G");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;


    int ni = 16;
    int nj = 18;
    int nk = 20;
    int nl = 22;
    int nm = 24;

    double E[16][18];
    double A[16][20];
    double B[20][18];
    double F[18][22];
    double C[18][24];
    double D[24][22];
    double G[16][22];

    init_array(ni, nj, nk, nl, nm, A, B, C, D);

    kernel_3mm(E, A, B, F, C, D, G);

    print_array(ni, nl, G);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}