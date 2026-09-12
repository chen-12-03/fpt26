
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

#include "add_round_key.h"

void phex(uint8_t *str) {

    uint8_t len = 16;
    unsigned char i;
    for (i = 0; i < len; ++i)
        printf("%.2x", str[i]);
    printf("\n");
}
// This function adds the round key to state.
int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;

    uint8_t rkey[176];
    for (int i = 0; i < 176; i++) {
        rkey[i] = i;
    }

    state_t state = {{0x99, 0xaa, 0xaa, 0xaa},
                     {0xaa, 0xaa, 0xaa, 0xaa},
                     {0xaa, 0xaa, 0xaa, 0xaa},
                     {0xaa, 0xaa, 0xaa, 0xaa}};

    AddRoundKey(0, &state, rkey);
    phex((uint8_t *)state);
    AddRoundKey(1, &state, rkey);
    phex((uint8_t *)state);
    AddRoundKey(2, &state, rkey);
    phex((uint8_t *)state);
    AddRoundKey(3, &state, rkey);
    phex((uint8_t *)state);
    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}