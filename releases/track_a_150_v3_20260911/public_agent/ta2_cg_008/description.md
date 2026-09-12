# ta2_cg_008

Implement the missing HLS kernel.

Edit only `3mm.cpp`. Preserve the top-level function `kernel_3mm`, its signature, headers, file names, data types, and testbench contract. The target is Alveo U55C under Vitis 2025.2 with a minimum frequency of 100 MHz.

## Kernel specification

Kernel Description:
The `kernel_3mm` is a linear algebra kernel. It takes six input matrices, `A`, `B`, `C`, `D`, `E`, and `F`, and produces one output matrix `G`. The kernel computes the matrix product `G = (A.B).(C.D)`, where `.` denotes matrix multiplication. The kernel is implemented using three nested loops, each performing a matrix multiplication.

It takes the following as inputs,

- $A: P \times Q$ matrix
- $B: Q \times R$ matrix
- $C: R \times S$ matrix
- $D: S \times T$ matrix

and gives the following as output:

- $G: P \times T$ matrix, where $G = (A.B).(C.D)$

---

Top-Level Function: `kernel_3mm`

Complete Function Signature of the Top-Level Function:
`void kernel_3mm(double E[16][18], double A[16][20], double B[20][18], double F[18][22], double C[18][24], double D[24][22], double G[16][22]);`

Inputs:
- `A`: a `16x20` matrix
- `B`: a `20x18` matrix
- `C`: an `18x24` matrix
- `D`: a `24x22` matrix
- `E`: a `16x18` matrix (intermediate result)
- `F`: an `18x22` matrix (intermediate result)

Outputs:
- `G`: a `16x22` matrix, the result of the matrix product `(A.B).(C.D)`

Important Data Structures and Data Types:
- `double`: a 64-bit floating-point number, used to represent matrix elements
- `matrix`: a 2D array of `double` values, used to represent matrices

Sub-Components:
- None
