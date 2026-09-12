# Track-A v2: code_generation

Implement the complete HLS kernel from the specification.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

Kernel Description:
The CORDIC (Coordinate Rotation Digital Computer) algorithm is a highly efficient iterative method used for computing trigonometric functions such as sine and cosine. This implementation of the CORDIC algorithm is designed to compute the sine and cosine of a given angle in radians. The algorithm iteratively rotates a vector in the Cartesian plane towards the desired angle, using a series of predefined rotations. The CORDIC algorithm is particularly useful in hardware implementations due to its simplicity and low computational complexity, as it primarily relies on additions, subtractions, and bit shifts.

The algorithm operates by maintaining a vector that starts along the x-axis and rotates it towards the target angle by a series of smaller angles. Each iteration involves a rotation by a fixed angle, which is chosen from a predefined table of angles. The angle table is generated such that the sum of the angles converges to the desired angle. The CORDIC algorithm can be configured for different modes, such as rotation mode, vectoring mode, and hyperbolic mode. In this implementation, we are using the rotation mode to compute sine and cosine.

The CORDIC algorithm can be described by the following equations:
- \( x_{i+1} = x_i - y_i \cdot d_i \cdot 2^{-i} \)
- \( y_{i+1} = y_i + x_i \cdot d_i \cdot 2^{-i} \)
- \( \theta_{i+1} = \theta_i - \mathrm{phase}[i] \cdot d_i \)

Where:
- \( x_i \) and \( y_i \) are the coordinates of the vector at iteration \( i \).
- \( \theta_i \) is the angle of the vector at iteration \( i \).
- \( d_i \) is the direction of rotation, which is +1 if the target angle is greater than the current angle, and -1 otherwise.
- \( \theta_i \) is the angle of rotation at iteration \( i \).

The algorithm iterates for a fixed number of iterations (32 in this case) to achieve the desired precision. The initial vector is scaled by the inverse CORDIC gain so that the final magnitude is approximately one. For many iterations this compensation factor is approximately 0.607252935; the exact benchmark literal and fixed-point sequence are specified below.

### Normative fixed-point computation contract

The benchmark uses the fixed-point operation sequence below, including its quantization points. Initialize `COS_SIN_TYPE current_cos = 0.60735`, `COS_SIN_TYPE current_sin = 0.0`, and `COS_SIN_TYPE factor = 1.0`. For each `j` from 0 to `NUM_ITERATIONS - 1`, choose integer `sigma = -1` when the current `theta` is negative and `+1` otherwise (zero selects `+1`). Compute `COS_SIN_TYPE cos_shift = current_cos * sigma * factor` and `COS_SIN_TYPE sin_shift = current_sin * sigma * factor` from the pre-update values. Then assign `current_cos = current_cos - sin_shift`, `current_sin = current_sin + cos_shift`, `theta = theta - sigma * cordic_phase[j]`, and `factor = factor / 2`, in that order. After the loop, assign `s = current_sin` and `c = current_cos`.

Use `COS_SIN_TYPE` for the vector and factor intermediates and `THETA_TYPE` for the residual angle. The literal `0.60735` and the multiply-by-`factor` sequence are part of the exact benchmark contract; a mathematically equivalent floating-point constant or an integer shift applied to `THETA_TYPE` need not quantize to the same result.

---

Top-Level Function: `cordic`

Complete Function Signature of the Top-Level Function:
`void cordic(THETA_TYPE theta, COS_SIN_TYPE &s, COS_SIN_TYPE &c);`

Inputs:
- `theta`: The input angle in radians for which the sine and cosine are to be computed. The data type is `THETA_TYPE`, which is defined as `ap_fixed<12, 2>`. This means the angle is represented with 12 bits, where 2 bits are used for the integer part and 10 bits for the fractional part.

Outputs:
- `s`: The computed sine of the input angle. The data type is `COS_SIN_TYPE`, which is defined as `ap_fixed<12, 2>`. This means the sine value is represented with 12 bits, where 2 bits are used for the integer part and 10 bits for the fractional part.
- `c`: The computed cosine of the input angle. The data type is `COS_SIN_TYPE`, which is defined as `ap_fixed<12, 2>`. This means the cosine value is represented with 12 bits, where 2 bits are used for the integer part and 10 bits for the fractional part.

Important Data Structures and Data Types:
- `THETA_TYPE`: Represents the angle in radians. It is defined as `ap_fixed<12, 2>`, which means it has 12 bits with 2 bits for the integer part and 10 bits for the fractional part.
- `COS_SIN_TYPE`: Represents the sine and cosine values. It is defined as `ap_fixed<12, 2>`, which means it has 12 bits with 2 bits for the integer part and 10 bits for the fractional part.
- `cordic_phase`: An array of predefined angles used in the CORDIC iterations. It is defined as an array of `THETA_TYPE` with 64 elements. Each element represents a fixed angle used in the iterative process.

Sub-Components:
- None
