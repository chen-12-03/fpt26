
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

/*
 * Copyright 2022 Xilinx, Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "fp_mul_pow2.h"

#define NUM_TEST_ITERS 16

// Simple test program to validate SW models and for re-use in RTL co-simulation
int main(void) {
    if (!std::freopen("track_a_public_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_public_stderr.actual", "wb", stderr)) return 98;

  double test_val = 3.5;
  int16_t test_exp = -15;
  double_num_t hw_result, sw_result;
  unsigned i, err_cnt = 0;

  for (i = 0; i < NUM_TEST_ITERS; i++) {
    // Get result from HW version
    hw_result.fp_num = double_mul_pow2(test_val, test_exp);
    // Generate expected result
    sw_result.fp_num = test_val * pow(2.0, test_exp);
    // Print out result
    printf("hw_result = %13g : bits = 0x%016llX : ", hw_result.fp_num,
           (unsigned long long)hw_result.raw_bits);
    printf("sign = %c, exp = %5d, mant = 0x%014llX", hw_result.sign ? '-' : '+',
           (int)hw_result.bexp - 1023, (unsigned long long)hw_result.mant);
    // Check for mismatch
    if (hw_result.fp_num != sw_result.fp_num) {
      err_cnt++;
      printf(" !!! MISMATCH !!!\n");
      printf("sw_result = %13g : bits = 0x%016llX : ", sw_result.fp_num,
             (unsigned long long)sw_result.raw_bits);
      printf("sign = %c, exp = %5d, mant = 0x%014llX\n",
             sw_result.sign ? '-' : '+', (int)sw_result.bexp - 1023,
             (unsigned long long)sw_result.mant);
    } else {
      printf("\n");
    }
    // Generate new inputs
    test_val = ((RAND_MAX / 2) - rand()) / (float)rand();
    test_exp = 1023 - (rand() & 0x7FF);
  }

  // Print final test status
  if (err_cnt)
    printf("!!! TEST FAILED !!!\n");
  else
    printf("*** Test passed ***\n");
  // Return 0 only on success
  if (err_cnt)
    return 1;
  else
    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_public_stdout.actual", "track_a_public_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_public_stderr.actual", "track_a_public_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}
