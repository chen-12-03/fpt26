
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

#include "bicg.h"

void init_array(int m, int n, double A[42][38], double r[42], double p[38]) {
    int i, j;

    for (i = 0; i < m; i++)
        p[i] = ((double)(i % m) / m) + (double)(((i * i + 3 * i) + 7) % 11) / 13.0;
    for (i = 0; i < n; i++) {
        r[i] = (double)(i % n) / n;
        for (j = 0; j < m; j++)
            A[i][j] = (double)(i * (j + 1) % n) / n;
    }
}

void print_array(int m, int n, double s[38], double q[42])

{
    int i;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "s");
    for (i = 0; i < m; i++) {
        if (i % 20 == 0)
            fprintf(stderr, "\n");
        fprintf(stderr, "%0.6lf ", s[i]);
    }
    fprintf(stderr, "\nend   dump: %s\n", "s");
    fprintf(stderr, "begin dump: %s", "q");
    for (i = 0; i < n; i++) {
        if (i % 20 == 0)
            fprintf(stderr, "\n");
        fprintf(stderr, "%0.6lf ", q[i]);
    }
    fprintf(stderr, "\nend   dump: %s\n", "q");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;


    int n = 42;
    int m = 38;

    double A[42][38];
    double s[38];
    double q[42];
    double p[38];
    double r[42];

    init_array(m, n, A, r, p);

    kernel_bicg(A, s, q, p, r);

    print_array(m, n, s, q);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}