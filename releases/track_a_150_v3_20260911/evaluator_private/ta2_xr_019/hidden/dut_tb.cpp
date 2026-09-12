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

#include "example.h"
#include <iostream>

int main() {
    A arr[N + 1], out[N + 1];
    for (unsigned i = 0; i < N; i++) {
        arr[i].c = 3 * i + 1;
        arr[i].i = 5 * i + 7;
    }
    arr[N].c = 0x5A;
    arr[N].i = 0x13579BDF;
    out[N].c = 0x2C;
    out[N].i = 0x2468ACE;

    dut(arr, out);
    for (unsigned i = 0; i < N; i++) {
        std::cout << i << ": " << int(out[i].c) << ", " << out[i].i
                  << std::endl;
        if (out[i].c != 3 * i + 1 || out[i].i != 5 * i + 7)
            return 1;
    }
    if (out[N].c != 0x2C || out[N].i != 0x2468ACE) {
        std::cerr << "output boundary canary was modified" << std::endl;
        return 1;
    }
    return 0;
}
