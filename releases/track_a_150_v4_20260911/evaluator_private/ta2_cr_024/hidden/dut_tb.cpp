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

int main() {
    A a;
    long expected = 0;
    for (unsigned i = 0; i < N; i++)
        a.s_in.write(3 * i + 2);
    for (unsigned i = 0; i < N; i++)
        a.arr[i] = 5 * i + 7;
    for (unsigned i = 0; i < N; ++i)
        expected += (3 * i + 2) + (5 * i + 7);

    auto ret = dut(a);
    if (ret != expected) {
        std::cerr << "FAIL: hidden struct sum mismatch" << std::endl;
        return 1;
    }
    return 0;
}
