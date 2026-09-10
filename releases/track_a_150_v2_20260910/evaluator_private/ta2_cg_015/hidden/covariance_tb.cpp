
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

#include "covariance.h"

void init_array(int m, int n, double *float_n, double data[32][28]) {
    int i, j;

    *float_n = (double)n;

    for (i = 0; i < 32; i++)
        for (j = 0; j < 28; j++)
            data[i][j] = (((double)i * j) / 28) + (double)(((i * i + 3 * i) + (j * j + 3 * j) + 7) % 11) / 13.0;
}

void print_array(int m, double cov[28][28])

{
    int i, j;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "cov");
    for (i = 0; i < m; i++)
        for (j = 0; j < m; j++) {
            if ((i * m + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%0.6lf ", cov[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "cov");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;


    int n = 32;
    int m = 28;

    double float_n;
    double data[32][28];
    double cov[28][28];
    double mean[28];

    init_array(m, n, &float_n, data);

    kernel_covariance(float_n, data, cov, mean);

    print_array(m, cov);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}