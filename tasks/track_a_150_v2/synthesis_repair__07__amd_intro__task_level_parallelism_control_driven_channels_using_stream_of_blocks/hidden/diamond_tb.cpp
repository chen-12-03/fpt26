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
#include "diamond.h"
#include <fstream>
#include <iostream>
using namespace std;

int main() {

    hls::stream<data_t> test;
    hls::stream<data_t> outcome;

    int retval = 0;
    ofstream FILE;

    // Save the results to a file
    FILE.open("result.dat");

    // Executing the DUT thrice
    for (int iter = 0; iter < 3; iter++) {

        // Init test vector
        for (int i = 0; i < N; i++) {
            test.write(3 * i + 7);
        }

        // Execute DUT
        diamond(test, outcome);

        // Display the results
        for (int i = 0; i < N; i++) {
            data_t outp = outcome.read();
            cout << "Series " << iter;
            cout << " Outcome: " << (int)outp << endl;
            FILE << (int)outp << endl;
            if ((int)outp != ((45 * i + 130) & 0xff)) retval = 1;
        }
    }

    FILE.close();

    // The hidden oracle is the independent closed-form composition:
    // (3*x + 25) + 2*(6*x) = 15*x + 25.
    if (retval) cout << "Test failed  !!!" << endl;
    else cout << "Test passed !" << endl;

    // Return 0 if the test passed
    return retval;
}
