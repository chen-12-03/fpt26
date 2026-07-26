open_project synth_proj
add_files double_mul_pow2.cpp
open_solution sol -flow_target vivado
set_top double_mul_pow2
set_part xcu55c-fsvh2892-2L-e
create_clock -period 5.0 -name clk_default
config_compile -unsafe_math_optimizations
csynth_design
exit
