open_project csim_proj
add_files -tb test_kernel_maxi_512bit_6.cpp
add_files -tb test_kernel_maxi_512bit_6_tb.cpp
open_solution sol -flow_target vivado
set_top test_kernel_maxi_512bit_6
set_part xcu55c-fsvh2892-2L-e
create_clock -period 5.0 -name clk_default
csim_design -setup
exit
