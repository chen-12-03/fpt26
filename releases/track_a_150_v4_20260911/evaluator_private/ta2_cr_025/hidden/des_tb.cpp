#include <memory.h>
#include <stdio.h>

#include "des.h"

int main() {
    des_block_t pt1 = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
    unsigned char key1[DES_BLOCK_SIZE] = {0x00, 0x00, 0x00, 0x00,
                                                  0x00, 0x00, 0x00, 0x00};
    // Independent all-zero key/plaintext known-answer vector.
    const des_block_t expected = {0x8C, 0xA6, 0x4D, 0xE9, 0xC1, 0xB1, 0x23, 0xA7};

    des_key_t schedule;
    des_block_t buf;

    des_key_setup(key1, schedule, DES_ENCRYPT);
    des_crypt(&pt1, &buf, &schedule);

    if (memcmp(buf, expected, DES_BLOCK_SIZE) != 0) {
        fprintf(stderr, "FAIL: hidden DES known-answer vector mismatch; got=");
        for (int i = 0; i < DES_BLOCK_SIZE; ++i)
            fprintf(stderr, "%02X", buf[i]);
        fprintf(stderr, "\n");
        return 1;
    }

    // FIPS 46-3 example vector.  Unlike the all-zero vector, its round
    // subkeys are nonuniform, so reversed or malformed key schedules cannot
    // accidentally pass.
    des_block_t pt2 = {0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF};
    unsigned char key2[DES_BLOCK_SIZE] = {
        0x13, 0x34, 0x57, 0x79, 0x9B, 0xBC, 0xDF, 0xF1};
    const des_block_t ct2 = {
        0x85, 0xE8, 0x13, 0x54, 0x0F, 0x0A, 0xB4, 0x05};

    des_key_setup(key2, schedule, DES_ENCRYPT);
    des_crypt(&pt2, &buf, &schedule);
    if (memcmp(buf, ct2, DES_BLOCK_SIZE) != 0) {
        fprintf(stderr, "FAIL: hidden DES nonzero encryption vector mismatch\n");
        return 1;
    }

    des_key_setup(key2, schedule, DES_DECRYPT);
    des_block_t encrypted;
    memcpy(encrypted, ct2, DES_BLOCK_SIZE);
    des_crypt(&encrypted, &buf, &schedule);
    if (memcmp(buf, pt2, DES_BLOCK_SIZE) != 0) {
        fprintf(stderr, "FAIL: hidden DES decryption vector mismatch\n");
        return 1;
    }

    // NIST variable-key known-answer vector: the most significant key bit is
    // set.  This also exercises permutation-table boundary mistakes that the
    // all-zero and 0x13... keys may mask.
    des_block_t pt3 = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
    unsigned char key3[DES_BLOCK_SIZE] = {
        0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
    const des_block_t ct3 = {
        0x95, 0xA8, 0xD7, 0x28, 0x13, 0xDA, 0xA9, 0x4D};
    des_key_setup(key3, schedule, DES_ENCRYPT);
    des_crypt(&pt3, &buf, &schedule);
    if (memcmp(buf, ct3, DES_BLOCK_SIZE) != 0) {
        fprintf(stderr, "FAIL: hidden DES variable-key vector mismatch\n");
        return 1;
    }
    return 0;
}
