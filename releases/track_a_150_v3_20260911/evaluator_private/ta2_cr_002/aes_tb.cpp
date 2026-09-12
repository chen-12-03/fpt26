
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

#include "aes.h"

// prints string as hex
void phex(uint8_t *str) {

    uint8_t len = 16;
    unsigned char i;
    for (i = 0; i < len; ++i)
        printf("%.2x", str[i]);
    printf("\n");
}

int main() {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;

    struct AES_ctx ctx;
    uint8_t key[16] = {0x22,
                       0x22,
                       0x33,
                       0x44,
                       0x55,
                       0x66,
                       0x77,
                       0x88,
                       0x99,
                       0xaa,
                       0xbb,
                       0xcc,
                       0xdd,
                       0xee,
                       0xff,
                       0x00};
    AES_init_ctx(&ctx, key);
    state_t state = {{0xaa, 0xbb, 0xcc, 0xdd},
                     {0xab, 0xa1, 0x1a, 0xba},
                     {0xb0, 0xc1, 0xd2, 0xe4},
                     {0xbd, 0xaf, 0xfa, 0xff}};
    Cipher(&state, &ctx.RoundKey);

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
