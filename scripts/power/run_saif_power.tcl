# Common-period power runs for one design: vectorless, and SAIF-annotated with each
# stimulus set. Driven by scripts/power/run_power.py through environment variables:
#   KYBER_DESIGN  shared_pe | per_phase_baseline
#   KYBER_PERIOD  common clock period in ns
#   KYBER_SAIF_MANUSCRIPT / KYBER_SAIF_RANDOM   root-relative SAIF files (optional)
source [file join [file dirname [file normalize [info script]]] .. synthesis flow_common.tcl]
set design $::env(KYBER_DESIGN)
set period $::env(KYBER_PERIOD)
set ptag [kyber_tag $period]
set strip "tb_polymul_functional/dut"

kyber_impl $design $period vecless_$ptag 0
if {[info exists ::env(KYBER_SAIF_MANUSCRIPT)] && [file exists $::env(KYBER_SAIF_MANUSCRIPT)]} {
    kyber_impl $design $period saif_$ptag 0 $::env(KYBER_SAIF_MANUSCRIPT) $strip
}
if {[info exists ::env(KYBER_SAIF_RANDOM)] && [file exists $::env(KYBER_SAIF_RANDOM)]} {
    kyber_impl $design $period saifrand_$ptag 0 $::env(KYBER_SAIF_RANDOM) $strip
}
puts "=== power runs complete for $design at $period ns ==="
