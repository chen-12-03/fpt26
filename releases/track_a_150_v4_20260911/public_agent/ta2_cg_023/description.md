# ta2_cg_023

Implement the missing HLS kernel.

Edit only `runs.cpp`. Preserve the top-level function `Runs`, its signature, headers, file names, data types, and testbench contract. The target is Alveo U55C under Vitis 2025.2 with a minimum frequency of 100 MHz.

## Kernel specification

Kernel Description:
The `Runs` kernel is designed to analyze a binary array `epsilon` of size 65535 and compute two metrics: the number of ones (`S`) and the number of runs (`V`). A "run" is defined as a contiguous sequence of identical values (either all zeros or all ones). The kernel iterates through the `epsilon` array to count the number of ones and the number of transitions between zeros and ones. The results are returned through pointer references to `res_S` and `res_V`.

---

Top-Level Function: `Runs`

Complete Function Signature of the Top-Level Function:
`void Runs(int *res_S, int *res_V, int epsilon[N]);`

Inputs:
- `res_S`: A pointer to an integer where the number of ones in the `epsilon` array will be stored.
- `res_V`: A pointer to an integer where the number of runs in the `epsilon` array will be stored.
- `epsilon`: An array of integers of size 65535, where each element is either 0 or 1.

Outputs:
- `res_S`: The number of ones in the `epsilon` array.
- `res_V`: The number of runs in the `epsilon` array.

Important Data Structures and Data Types:
- `epsilon`: An array of integers of size 65535, where each element is either 0 or 1. This array is used as input to the kernel to compute the number of ones and runs.

Sub-Components:
- None
