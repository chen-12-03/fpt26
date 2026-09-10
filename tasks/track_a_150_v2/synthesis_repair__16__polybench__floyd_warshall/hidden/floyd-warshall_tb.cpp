
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

#include "floyd-warshall.h"

void init_array(int n, int path[60][60]) {
    int i, j;

    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++) {
            path[i][j] = (i * j % 7 + 1) + (double)(((i * i + 3 * i) + (j * j + 3 * j) + 7) % 11) / 13.0;
            if ((i + j) % 13 == 0 || (i + j) % 7 == 0 || (i + j) % 11 == 0)
                path[i][j] = 999;
        }
}

void print_array(int n, int path[60][60])

{
    int i, j;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "path");
    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++) {
            if ((i * n + j) % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%d ", path[i][j]);
        }
    fprintf(stderr, "\nend   dump: %s\n", "path");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;


    int n = 60;

    int path[60][60];

    init_array(n, path);

    kernel_floyd_warshall(path);

    print_array(n, path);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}