# Track-A v2: code_generation

Implement the complete HLS kernel from the specification.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

Kernel Description:
The Durbin kernel is an algorithm for solving Yule-Walker equations, which is a special case of Toeplitz systems. It takes a vector `r` of length `N` as input and produces a vector `y` of length `N` as output, such that `Ty = -r` where `T` is a symmetric, unit-diagonal, Toeplitz matrix defined by the vector `[1, r_0, ..., r_{N-1}]`. The algorithm is a direct implementation of the Durbin algorithm described in a book by Golub and Van Loan.

It takes the following as input,

- $r$: vector of length $N$.

and gives the following as output:

- $y$: vector of length $N$

such that $Ty = -r$ where $T$ is a symmetric, unit-diagonal, Toeplitz matrix defined by the vector $[1,r_0, \ldots ,r_{N-1}]$.
The C reference implementation is a direct implementation of the algorithm described in a book by Golub and Van Loan. The book mentions that a vector can be removed to use less space, but the implementation retains this vector.

### Normative computation contract

Use a temporary vector `z[40]` and the following recurrence in the stated order. Initialize `y[0] = -r[0]`, `beta = 1.0`, and `alpha = -r[0]`. For each `k = 1..39`, first set `beta = (1 - alpha*alpha) * beta`. Set `sum = 0.0` and accumulate `sum += r[k-i-1] * y[i]` for `i = 0..k-1`; then set `alpha = -(r[k] + sum) / beta`. Compute every `z[i] = y[i] + alpha * y[k-i-1]` for `i = 0..k-1` before copying `z[0..k-1]` back into `y[0..k-1]`, and finally assign `y[k] = alpha`. The temporary-vector separation is required because an in-place forward update changes later operands.

---

Top-Level Function: `kernel_durbin`

Complete Function Signature of the Top-Level Function:
`void kernel_durbin(double r[40], double y[40]);`

Inputs:
- `r`: a vector of length `N` (40 in this implementation) containing the input values.

Outputs:
- `y`: a vector of length `N` (40 in this implementation) containing the output values.

Important Data Structures and Data Types:
- `double`: a 64-bit floating-point number used to represent the input and output values.

Sub-Components:
- None
