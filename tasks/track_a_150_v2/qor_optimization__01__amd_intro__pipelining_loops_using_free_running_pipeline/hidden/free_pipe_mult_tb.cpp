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
#include <stdlib.h>
#include "free_pipe_mult.h"

#include <cstdlib>
#include <fstream>
#include <iostream>
using namespace std;

int main() {

    data_t Atest[SZ];
    data_t total;
    stream<data_t> strm;

    int retval = 0;
    ofstream FILE;

    // Create input data
    for (int i = 0; i < SZ; ++i) {
        Atest[i] = 2 * i + 3;
        strm << 5 * i - 4;
        cout << Atest[i] << endl;
    }
    // Save the results to a file
    FILE.open("result.dat");

    // Call the function
    free_pipe_mult(Atest, strm, total);

    // Save output data
    cout << "Result: " << total << endl;
    FILE << total << endl;
    FILE.close();

    // Independent sum: sum((2i+3)+i+(5i-4)), i in [0,SZ).
    retval = (total == 216) ? 0 : 1;

    // Return 0 if the test passes
    return retval;
}
