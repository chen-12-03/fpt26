
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

#include "cordic.h"

using namespace std;
// #define M_PI 3.1415926536897932384626

double abs_double(double var) {
    if (var < 0)
        var = -var;
    return var;
}
int main(int argc, char **argv) {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;


    FILE *fp;

    COS_SIN_TYPE s;    // sine
    COS_SIN_TYPE c;    // cos
    THETA_TYPE radian; // radian versuin of degree

    // zs=sin, zc=cos using math.h in VivadoHLS
    double zs, zc; // sine and cos values calculated from math.

    // Error checking
    double Total_Error_Sin = 0.0;
    double Total_error_Cos = 0.0;
    double error_sin = 0.0, error_cos = 0.0;

    fp = fopen("out.dat", "w");
    for (int i = 1; i < NUM_DEGREE; i++) {
        radian = i * M_PI / 183;
        cordic(radian, s, c);
        zs = sin((double)radian);
        zc = cos((double)radian);
        error_sin = (abs_double((double)s - zs) / zs) * 100.0;
        error_cos = (abs_double((double)c - zc) / zc) * 100.0;
        Total_Error_Sin = Total_Error_Sin + error_sin;
        Total_error_Cos = Total_error_Cos + error_cos;

        fprintf(
            fp,
            "degree=%d, radian=%f, cos=%f, sin=%f\n",
            i,
            (double)radian,
            (double)c,
            (double)s);
    }

    fclose(fp);

    printf(
        "Total_Error_Sin=%f, Total_error_Cos=%f, \n",
        Total_Error_Sin,
        Total_error_Cos);
    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    track_a_mismatch |= track_a_compare_file("out.dat", "track_a_hidden_output_0.golden");
    return track_a_mismatch ? 1 : 0;
}