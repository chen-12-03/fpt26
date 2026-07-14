# Official Harness Backup

This directory is the read-only backup of the official harness files currently present in this repository.

## Source and Purpose

The files were copied verbatim from the existing local harness entry points under `fpt26-agent/`:

- `vitis.dockerfile`
- `run-vitis.sh`
- `run.tcl`

The task statement identifies these files as the official harness files. The repository documentation also points to the FPT26 Track-A reference harness URL, but this backup was made from the local files only; no remote source was fetched or compared in this task.

These files are kept here as a stable reference for later wrapper work. Do not edit these backed-up harness files directly.

## Current Real Call Chain

The current local call chain is:

```text
run-vitis.sh
  -> docker run IMAGE=vitis_runtime:2025.2
  -> mount host Vitis, XRT, platform directory, HOME, and current working directory
  -> source $XILINX_VITIS/settings64.sh
  -> source $XILINX_XRT/setup.sh
  -> export PLATFORM
  -> cd to the host working directory
  -> run the user-supplied command, or open an interactive bash shell
```

The Tcl entry point documents these intended commands:

```text
vitis_hls -f run.tcl
vitis-run --mode hls --tcl run.tcl
```

`run.tcl` currently performs:

```text
open_project hls_prj
set_top {top}
open_solution hls -flow_target vivado
add_files kernel.cpp
add_files -tb host.cpp -cflags "-O2 -pthread"
set_part {part}
create_clock -period {period} -name default
csynth_design
optional cosim_design when COSIM=1
```

## Read-Only Rule

- Treat this directory as immutable reference material.
- Do not modify the copied official files in this directory.
- Do not generate Vitis projects, logs, reports, caches, or other run products here.
- Put all adaptations, parameterization, run-directory management, and report handling under `harness/wrapper/`.

## Known Placeholders, Dependencies, and Limits

- `run.tcl` still contains unresolved placeholders: `{top}`, `{part}`, and `{period}`.
- `run.tcl` hard-codes `kernel.cpp`, `host.cpp`, `hls_prj`, solution name `hls`, and `csynth_design`.
- `run.tcl` references `host.cpp`, but no `host.cpp` exists in the current source tree.
- `run.tcl` does not run `csim_design`; it runs synthesis and optional cosimulation only.
- `run.tcl` writes the Vitis project to `hls_prj` in the current working directory.
- `run-vitis.sh` defaults to image `vitis_runtime:2025.2`.
- `run-vitis.sh` defaults Vitis to `/tools/Xilinx/Vitis/2025.2`.
- `run-vitis.sh` defaults XRT to `/opt/xilinx/xrt`.
- `run-vitis.sh` defaults the platform to `/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm`.
- `run-vitis.sh` bind-mounts `/tools/Xilinx`, `/opt/xilinx/platforms`, `$HOME`, and the current working directory.
- Existing logs show Vitis HLS 2025.2 was started, but the run failed because `host.cpp` was missing and `set_part part` used the unresolved placeholder `part`.

## Excluded From Backup

The following local files/directories were not backed up as official harness source:

- `kernel.cpp`: example kernel, not identified as an official harness entry file for this task.
- `hls_prj/`: generated Vitis project/output directory.
- `logs/`: generated run logs.
- `*:Zone.Identifier`: Windows/WSL metadata sidecar files, not identified as harness source.
- `docs/` and `scripts/`: project documentation and helper material, not copied as official harness source.
