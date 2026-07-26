open_project synth_proj
add_files hamming_window.cpp
open_solution sol -flow_target vivado
set_top hamming_window
set_part xcu55c-fsvh2892-2L-e
create_clock -period 5.0 -name clk_default
config_compile -unsafe_math_optimizations
csynth_design
exit
