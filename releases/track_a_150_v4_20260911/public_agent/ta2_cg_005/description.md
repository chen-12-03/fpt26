# ta2_cg_005

Implement the missing HLS kernel.

Edit only `nussinov.cpp`. Preserve the top-level function `kernel_nussinov`, its signature, headers, file names, data types, and testbench contract. The target is Alveo U55C under Vitis 2025.2 with a minimum frequency of 100 MHz.

## Kernel specification

Kernel Description:
The Nussinov kernel is an algorithm for predicting RNA folding, which is an instance of dynamic programming. It takes an RNA sequence as input and produces a dynamic programming table as output. The table is filled using a recursive formula that considers the maximum score of four possible cases: (1) the maximum score of the sub-problem without considering the current base pair, (2) the maximum score of the sub-problem without considering the current base, (3) the maximum score of the sub-problem with considering the current base pair, and (4) the maximum score of the sub-problem with considering the current base pair and the maximum score of the sub-problem without considering the current base pair.

It takes the following as input,

- `seq`: an RNA sequence of length $N$ encoded by integer values 0 through 3 in elements of type `char`.

and gives the following as output:

- `table`: $N \times N$ triangular matrix, which is the dynamic programming table.

The table is filled using the following formula:

$$
table(i,j) = \max
\begin{cases}
table(i+1,j) \\
table(i,j-1) \\
table(i+1,j-1) + w(i,j) \\
\max_{i < k < j}(table(i,k) + table(k+1,j))
\end{cases}
$$

where $w$ is the benchmark scoring function: it returns 1 exactly when the two numeric codes sum to 3, and 0 otherwise.

### Normative computation contract

In this benchmark, `seq` stores numeric base codes in a `char`; a pair scores one exactly when `seq[i] + seq[j] == 3`. Iterate `i` from 59 down to 0 and `j` from `i + 1` up to 59. Each `table[i][j]` retains the maximum of its incoming value, `table[i][j-1]`, `table[i+1][j]`, the paired subproblem, and every split `table[i][k] + table[k+1][j]` for `i < k < j`. The paired subproblem adds the one-point pair score only when `i < j - 1`; adjacent positions use `table[i+1][j-1]` without a score increment. Entries outside this upper-triangular update region are not reinitialized by the kernel.

---

Top-Level Function: `kernel_nussinov`

Complete Function Signature of the Top-Level Function:
`void kernel_nussinov(char seq[60], int table[60][60]);`

Inputs:
- `seq`: an RNA sequence of length 60 whose numeric codes 0 through 3 are stored in a 1D array of `char`.

Outputs:
- `table`: a 2D array of integers, representing the dynamic programming table. The table is a triangular matrix of size 60x60, where each element `table[i][j]` represents the maximum score of the sub-problem considering the RNA sequence from `i` to `j`.

Important Data Structures and Data Types:
- `seq`: a 1D array of characters, representing the RNA sequence.
- `table`: a 2D array of integers, representing the dynamic programming table.

Sub-Components:
- None
