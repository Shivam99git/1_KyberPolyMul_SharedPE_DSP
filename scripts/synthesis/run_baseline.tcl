# Per-phase reference core (rtl/per_phase_baseline/ntt_core_baseline.v): same FSM, memories
# and schedule as the shared core, but four dedicated multipliers and six add/sub units.
#   vivado -mode batch -source scripts/synthesis/run_baseline.tcl
source [file join [file dirname [file normalize [info script]]] flow_common.tcl]
kyber_reset_design_dir per_phase_baseline
kyber_closure_relax per_phase_baseline
puts "=== per_phase_baseline flow complete: [kyber_relpath $::report_root]/per_phase_baseline ==="
