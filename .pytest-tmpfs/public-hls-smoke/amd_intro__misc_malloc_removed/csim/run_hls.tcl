open_project csim_proj
add_files -tb malloc_removed.cpp
add_files -tb malloc_removed_tb.cpp
open_solution sol -flow_target vivado
set_top malloc_removed
set_part xcu55c-fsvh2892-2L-e
create_clock -period 5.0 -name clk_default
csim_design -setup
exit
