# Track-A v2: code_generation

Implement the complete HLS kernel from the specification.

Only the kernel source may be changed. File names, headers, data types, top-level interfaces, and testbenches are fixed. Target Alveo U55C with Vitis 2025.2 and a minimum frequency of 100 MHz.

Expected initial state: `compile_fail`.

## Kernel specification

Kernel Description:
The `propagateFloat64NaN` kernel propagates a NaN from two IEEE-754 double-precision bit patterns. It is called with at least one NaN operand. Before selection, set the quiet bit (`0x0008000000000000`) in both operands. Select `b` when `b` is a signaling NaN; otherwise select `a` when `a` is a signaling NaN; otherwise select `b` when `b` is any NaN; otherwise select `a`.

The algorithm involves several steps:
1. **Check for NaN**: Determine if each input is a NaN by examining the exponent and fraction fields of the floating-point representation.
2. **Check for Signaling NaN**: Further classify NaNs into signaling and quiet NaNs by examining the payload bits.
3. **Quiet and propagate NaN**: Set the quiet bit in both operands, then use this exact priority order: signaling `b`, signaling `a`, any-NaN `b`, then `a`.

---

Top-Level Function: `propagateFloat64NaN`

Complete Function Signature of the Top-Level Function:
`float64 propagateFloat64NaN(float64 a, float64 b);`

Inputs:
- `a`: A double-precision floating-point number represented as an unsigned 64-bit integer (`float64`).
- `b`: A double-precision floating-point number represented as an unsigned 64-bit integer (`float64`).

Outputs:
- The function returns a double-precision floating-point number (`float64`) which is the result of the NaN propagation logic.

Important Data Structures and Data Types:
- `float64`: An unsigned 64-bit integer type representing a double-precision floating-point number.
- `flag`: An integer type used to represent boolean flags (0 or 1).

Sub-Components:
- `float64_is_nan`:
    - Signature: `flag float64_is_nan(float64 a);`
    - Details: This function checks if the given `float64` value is a NaN by examining the exponent field. A value is considered a NaN if the exponent is all 1s and the fraction is non-zero.
- `float64_is_signaling_nan`:
    - Signature: `flag float64_is_signaling_nan(float64 a);`
    - Details: This function checks if the given `float64` value is a signaling NaN by examining the exponent and payload fields. A value is considered a signaling NaN if the exponent is all 1s, the payload is non-zero, and the most significant payload bit is 0.
