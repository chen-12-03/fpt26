
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


#include <cstddef>
#include <cstdint>
#include <cstdio>

static unsigned long long track_a_hash_bytes(const void *address, std::size_t size) {
    const unsigned char *bytes = static_cast<const unsigned char *>(address);
    unsigned long long value = 1469598103934665603ULL;
    for (std::size_t index = 0; index < size; ++index) {
        value ^= bytes[index];
        value *= 1099511628211ULL;
    }
    return value;
}

/*
 * Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
 * Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
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
#include "fir_top.h"
#include <iostream>
#define N 3

int main()
{
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

    s_data_t in[INPUT_LENGTH] = {3,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19};
    m_data_t out[OUTPUT_LENGTH] = {0};
    int err=0; 
    m_data_t ref[INPUT_LENGTH * 3] = {
    0,6,12,14,13,17,27,31,35,39,43,47,51,55,59,63,67,71,75,79,
    0,2640,0,760,0,20,0,560,0,840,0,1120,0,1400,0,1680,0,1960,0,2240,
    0,57,0,25,0,113,0,1,0,9,0,17,0,25,0,33,0,41,0,49
    };
    for (int j = 0; j < N; ++j) {
        config_t config = j;
        fir_top(in, out, &config); 
        for(unsigned i = 0; i < OUTPUT_LENGTH; ++i)
        {
            std::cout << "out[" << i << "] in " << j << " is " << out[i] << " -- expected value is " <<  ref[i*2+1+INPUT_LENGTH*j] 
                << std::endl;
            if(out[i] != ref[i*2+1 + INPUT_LENGTH * j])
            {
                err++;
            }
        }
    }
    
    if (err > 0 )
        printf ("FAIL!!!!\n");
    else
        printf ("PASS!!!!\n");
    
    std::fprintf(stderr, "\nTRACK_A_OBSERVATION_BEGIN\n");
    std::fprintf(stderr, "in=%016llx\n", track_a_hash_bytes(&in, sizeof(in)));
    std::fprintf(stderr, "out=%016llx\n", track_a_hash_bytes(&out, sizeof(out)));
    std::fprintf(stderr, "ref=%016llx\n", track_a_hash_bytes(&ref, sizeof(ref)));
    std::fprintf(stderr, "TRACK_A_OBSERVATION_END\n");
    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}
