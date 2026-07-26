open_project csim_proj
add_files -tb cpp_template.cpp
add_files -tb cpp_template_tb.cpp
open_solution sol -flow_target vivado
set_top cpp_template
set_part xcu55c-fsvh2892-2L-e
create_clock -period 5.0 -name clk_default
csim_design -setup
exit
