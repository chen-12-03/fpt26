#include <memory.h>
#include <stdio.h>

#include "des.h"

int main() {
    des_block_t pt1 = {0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF};
    unsigned char key1[DES_BLOCK_SIZE] = {
        0x13, 0x34, 0x57, 0x79, 0x9B, 0xBC, 0xDF, 0xF1};
    // FIPS 46-3 known-answer vector.
    const des_block_t expected = {0x85, 0xE8, 0x13, 0x54, 0x0F, 0x0A, 0xB4, 0x05};

    des_key_t schedule;
    des_block_t buf;

    des_key_setup(key1, schedule, DES_ENCRYPT);
    des_crypt(&pt1, &buf, &schedule);

    if (memcmp(buf, expected, DES_BLOCK_SIZE) != 0) {
        fprintf(stderr, "FAIL: DES known-answer vector mismatch; got=");
        for (int i = 0; i < DES_BLOCK_SIZE; ++i)
            fprintf(stderr, "%02X", buf[i]);
        fprintf(stderr, "\n");
        return 1;
    }
    return 0;
}
