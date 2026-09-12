# ta2_cg_006

Implement the missing HLS kernel.

Edit only `heat-3d.cpp`. Preserve the top-level function `kernel_heat_3d`, its signature, headers, file names, data types, and testbench contract. The target is Alveo U55C under Vitis 2025.2 with a minimum frequency of 100 MHz.

## Kernel specification

Kernel Description:
The `kernel_heat_3d` design is a high-level synthesis implementation of the 3D heat equation algorithm. The algorithm updates the value of a 3D grid point based on the values of its neighboring points in the previous time step. The update equation is a discretized version of the heat equation, which describes how heat diffuses through a 3D space. The design consists of a nested loop structure that iterates over the 3D grid, updating the values of each point based on the values of its neighbors.

The main update is as follows:

$$
\begin{align*}
data^{t}_{(i,j,k)} = & \ data^{t-1}_{(i,j,k)} \\
& + 0.125 \cdot \left( data^{t-1}_{(i+1,j,k)} - 2 \cdot data^{t-1}_{(i,j,k)} + data^{t-1}_{(i-1,j,k)} \right) \\
& + 0.125 \cdot \left( data^{t-1}_{(i,j+1,k)} - 2 \cdot data^{t-1}_{(i,j,k)} + data^{t-1}_{(i,j-1,k)} \right) \\
& + 0.125 \cdot \left( data^{t-1}_{(i,j,k+1)} - 2 \cdot data^{t-1}_{(i,j,k)} + data^{t-1}_{(i,j,k-1)} \right)
\end{align*}
$$

The design assumes a fixed grid size of 10x10x10, and uses a fixed number of time steps (20). The input and output grids are represented as 3D arrays of doubles, with a size of 10x10x10. The design does not use any explicit data structures or sub-components beyond the top-level function.

### Normative computation contract

The kernel performs 20 complete ping-pong time steps. For each time step, first update every interior element `B[i][j][k]`, where `1 <= i,j,k < 9`, from the current `A` using the equation above. Then, in a separate second sweep of the same interior range, update `A[i][j][k]` from the newly updated `B` using the same equation. Both arrays are therefore input/output state. Boundary elements (any coordinate equal to 0 or 9) are never written and retain their incoming values. Do not replace the two sweeps with only one `A`-to-`B` update.

---

Top-Level Function: `kernel_heat_3d`

Complete Function Signature of the Top-Level Function:
`void kernel_heat_3d(double A[10][10][10], double B[10][10][10]);`

Inputs:
- `A`: a 3D array of doubles, representing the input grid at the previous time step
- `B`: a 3D array of doubles, representing the second ping-pong grid

Outputs:
- `A`: the updated first ping-pong grid after 20 complete time steps
- `B`: the updated second ping-pong grid after the final first sweep

Important Data Structures and Data Types:
- `double[10][10][10]`: a 3D array of doubles, representing the input and output grids

Sub-Components:
- None
