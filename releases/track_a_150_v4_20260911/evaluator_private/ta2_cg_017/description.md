# Track-A v2: code_generation

Implement the complete HLS kernel from the specification.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

Kernel Description:
The `kernel_fdtd_2d` kernel implements the simplified PolyBench Finite-Difference Time-Domain (FDTD) stencil for 2D data. It evolves three arrays, `ex`, `ey`, and `hz`, and injects the supplied fictitious source at the upper `ey` boundary. Because the arrays are updated in place, sweep order, loop bounds, and scalar coefficients are observable parts of the function.

### Normative computation contract

Execute exactly 20 time steps, `t = 0..19`, and perform the following four sweeps in this order during each step:

1. For every `j = 0..29`, set `ey[0][j] = _fict_[t]`.
2. For `i = 1..19` and `j = 0..29`, set `ey[i][j] = ey[i][j] - 0.5 * (hz[i][j] - hz[i-1][j])`.
3. For `i = 0..19` and `j = 1..29`, set `ex[i][j] = ex[i][j] - 0.5 * (hz[i][j] - hz[i][j-1])`.
4. For `i = 0..18` and `j = 0..28`, set `hz[i][j] = hz[i][j] - 0.7 * (ex[i][j+1] - ex[i][j] + ey[i+1][j] - ey[i][j])`.

Each sweep observes the updates completed by all preceding sweeps in the same time step. No other coefficient set, boundary update, or alternative Maxwell discretization is part of this benchmark.

---

Top-Level Function: `kernel_fdtd_2d`

Complete Function Signature of the Top-Level Function:
`void kernel_fdtd_2d(double ex[20][30], double ey[20][30], double hz[20][30], double _fict_[20]);`

Inputs:
- `ex`: a 2D array of size 20x30, representing the electric field in the x-direction.
- `ey`: a 2D array of size 20x30, representing the electric field in the y-direction.
- `hz`: a 2D array of size 20x30, representing the magnetic field in the z-direction.
- `_fict_`: a 1D array of size 20, representing the fictitious source term.

Outputs:
- `ex`: the updated electric field in the x-direction.
- `ey`: the updated electric field in the y-direction.
- `hz`: the updated magnetic field in the z-direction.

Important Data Structures and Data Types:
- `double[20][30]`: a 2D array of size 20x30, used to represent the electric and magnetic fields.
- `double[20]`: a 1D array of size 20, used to represent the fictitious source term.

Sub-Components:
- None
