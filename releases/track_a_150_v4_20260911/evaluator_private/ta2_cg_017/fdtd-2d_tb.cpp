
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

#include "fdtd-2d.h"

void init_array(
    int tmax,
    int nx,
    int ny,
    double ex[20][30],
    double ey[20][30],
    double hz[20][30],
    double _fict_[20]) {
    int i, j;

    for (i = 0; i < tmax; i++)
        _fict_[i] = ((double)i) + (double)(((i * i + 3 * i) + 5) % 7) / 17.0;
    for (i = 0; i < nx; i++)
        for (j = 0; j < ny; j++) {
            ex[i][j] = ((double)i * (j + 1)) / nx;
            ey[i][j] = ((double)i * (j + 2)) / ny;
            hz[i][j] = ((double)i * (j + 3)) / nx;
        }
}

void print_array(
    int nx,
    int ny,
    double ex[20][30],
    double ey[20][30],
    double hz[20][30]) {
    int i, j;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "ex");
    for (i = 0; i < nx; i++)
        for (j = 0; j < ny; j++) {
            if ((i * nx + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", ex[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "ex");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");

    fprintf(stderr, "begin dump: %s", "ey");
    for (i = 0; i < nx; i++)
        for (j = 0; j < ny; j++) {
            if ((i * nx + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", ey[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "ey");

    fprintf(stderr, "begin dump: %s", "hz");
    for (i = 0; i < nx; i++)
        for (j = 0; j < ny; j++) {
            if ((i * nx + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", hz[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "hz");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;


    int tmax = 20;
    int nx = 20;
    int ny = 30;

    double ex[20][30];
    double ey[20][30];
    double hz[20][30];
    double _fict_[20];

    init_array(tmax, nx, ny, ex, ey, hz, _fict_);

    kernel_fdtd_2d(ex, ey, hz, _fict_);

    print_array(nx, ny, ex, ey, hz);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}