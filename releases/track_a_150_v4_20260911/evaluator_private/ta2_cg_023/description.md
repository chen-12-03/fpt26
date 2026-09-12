# Track-A v2: code_generation

Implement the complete HLS kernel from the specification.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

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
