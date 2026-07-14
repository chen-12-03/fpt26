proc require_env {name} {
  if {![info exists ::env($name)] || $::env($name) eq ""} {
    error "Missing required environment variable: $name"
  }
  return $::env($name)
}

proc env_flag {name default_value} {
  if {![info exists ::env($name)] || $::env($name) eq ""} {
    return $default_value
  }
  return $::env($name)
}

set top [require_env TOP]
set source_file [file normalize [require_env SOURCE_FILE]]
set testbench_file [file normalize [require_env TESTBENCH_FILE]]
set csim_helper_file [env_flag CSIM_HELPER_FILE ""]
set hls_part [require_env HLS_PART]
set clock_period_ns [require_env HLS_CLOCK_PERIOD_NS]
set run_dir [file normalize [require_env RUN_DIR]]

set run_csim [env_flag RUN_CSIM 1]
set run_synth [env_flag RUN_SYNTH 1]
set run_cosim [env_flag RUN_COSIM 0]
set array_depth [env_flag HLS_ARRAY_DEPTH 16]
set project_dir [file normalize [env_flag RUN_PROJECT_DIR [file join $run_dir project]]]

if {![file exists $source_file]} {
  error "SOURCE_FILE does not exist: $source_file"
}
if {![file exists $testbench_file]} {
  error "TESTBENCH_FILE does not exist: $testbench_file"
}
if {$csim_helper_file ne ""} {
  set csim_helper_file [file normalize $csim_helper_file]
  if {![file exists $csim_helper_file]} {
    error "CSIM_HELPER_FILE does not exist: $csim_helper_file"
  }
}
if {$run_cosim ne "0"} {
  error "RUN_COSIM is not supported in the current baseline wrapper"
}

file mkdir $run_dir
file mkdir $project_dir
cd $run_dir

open_project $project_dir
set_top $top
open_solution solution1 -flow_target vivado
add_files $source_file
if {$run_csim ne "0" && $csim_helper_file ne ""} {
  add_files -tb $csim_helper_file -cflags "-O2"
}
if {$run_csim ne "0"} {
  add_files -tb $testbench_file -cflags "-O2"
}
set_part $hls_part
create_clock -period $clock_period_ns -name default
set_directive_interface -mode ap_memory -depth $array_depth $top a
set_directive_interface -mode ap_memory -depth $array_depth $top b
set_directive_interface -mode ap_memory -depth $array_depth $top c

if {$run_csim ne "0"} {
  csim_design
}
if {$run_synth ne "0"} {
  csynth_design
}

close_project
exit
