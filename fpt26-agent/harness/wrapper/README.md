# Harness Wrapper

This directory is reserved for all future adaptations around the official harness.

## Purpose

The official harness backup lives in `harness/official/` and must remain read-only. Any project-specific behavior should be implemented here instead, including later work such as:

- parameter validation and injection;
- isolated run directory creation;
- source and testbench staging;
- Vitis command execution;
- stdout and stderr log capture;
- report discovery;
- structured result generation.

No wrapper implementation is included yet. This task only creates the wrapper location and documents the current boundary.

## Current Real Call Chain

At the time this README was created, the repository still calls the original local harness files directly:

```text
fpt26-agent/run-vitis.sh
  -> docker run
  -> source Vitis and XRT setup scripts
  -> export PLATFORM
  -> user command such as `vitis_hls -f run.tcl`
  -> fpt26-agent/run.tcl
```

The backup copies are:

```text
harness/official/vitis.dockerfile
harness/official/run-vitis.sh
harness/official/run.tcl
```

The wrapper does not yet intercept this call chain.

## Rules for Later Work

- Do not edit files under `harness/official/`.
- Do not write generated Vitis projects, logs, reports, or caches under `harness/official/`.
- Keep generated run products in isolated run directories outside the official backup.
- Preserve the official harness launch behavior unless a later task explicitly changes it.
- Record unresolved placeholders, missing files, and environment assumptions instead of guessing them.

## Known Inputs for Future Wrapper Tasks

- Official shell entry: `harness/official/run-vitis.sh`
- Official Tcl entry: `harness/official/run.tcl`
- Official Dockerfile: `harness/official/vitis.dockerfile`
- Default Vitis version from shell entry: `2025.2`
- Default platform from shell entry: `xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm`
- Current missing testbench: `host.cpp`
- The wrapper Tcl obtains top, source, testbench, part, clock, and run
  directory from environment variables.
