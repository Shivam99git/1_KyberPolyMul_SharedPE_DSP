# Primary resource-shared single-PE core (rtl/shared_pe/ntt_core_shared.v), conventional
# two-cycle multiply-reduce.   vivado -mode batch -source scripts/synthesis/run_shared_pe.tcl
source [file join [file dirname [file normalize [info script]]] flow_common.tcl]
kyber_reset_design_dir shared_pe
kyber_closure_relax shared_pe
puts "=== shared_pe flow complete: [kyber_relpath $::report_root]/shared_pe ==="
