if {$argc != 1} {
  error "usage: verify-part.tcl <hls_part>"
}

set hls_part [lindex $argv 0]
set matches [get_parts -quiet $hls_part]
if {[llength $matches] != 1} {
  error "HLS_PART is not installed or is ambiguous: $hls_part"
}

puts "verified HLS_PART: $matches"
exit
