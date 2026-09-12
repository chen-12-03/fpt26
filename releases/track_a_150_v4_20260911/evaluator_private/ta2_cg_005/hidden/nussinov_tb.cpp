
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

#include "nussinov.h"

void init_array(int n, char seq[60], int table[60][60]) {
    int i, j;

    for (i = 0; i < n; i++) {
        seq[i] = ((char)((i + 1) % 4)) + (double)(((i * i + 3 * i) + 7) % 11) / 13.0;
    }

    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++)
            table[i][j] = 0;
}

void print_array(int n, int table[60][60])

{
    int i, j;
    int t = 0;

    fprintf(stderr, "==BEGIN DUMP_ARRAYS==\n");
    fprintf(stderr, "begin dump: %s", "table");
    for (i = 0; i < n; i++) {
        for (j = i; j < n; j++) {
            if (t % 20 == 0)
                fprintf(stderr, "\n");
            fprintf(stderr, "%d ", table[i][j]);
            t++;
        }
    }
    fprintf(stderr, "\nend   dump: %s\n", "table");
    fprintf(stderr, "==END   DUMP_ARRAYS==\n");
}

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;


    int n = 60;

    char seq[60];
    int table[60][60];

    init_array(n, seq, table);

    kernel_nussinov(seq, table);

    print_array(n, table);

    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}