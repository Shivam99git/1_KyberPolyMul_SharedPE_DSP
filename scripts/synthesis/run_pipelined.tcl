# Pipelined-Barrett shared-PE core: ntt_core_shared compiled with USE_PIPELINED_BARRETT
# (mult_unit -> mult_conventional_pipelined, three-cycle multiply-reduce).
#   vivado -mode batch -source scripts/synthesis/run_pipelined.tcl
source [file join [file dirname [file normalize [info script]]] flow_common.tcl]
kyber_reset_design_dir pipelined_barrett
kyber_closure_tighten pipelined_barrett 9.500 0.2 12
puts "=== pipelined_barrett flow complete: [kyber_relpath $::report_root]/pipelined_barrett ==="
