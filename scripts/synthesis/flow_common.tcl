# ============================================================================
# Shared procedures for the non-interactive Vivado flows.
#
#   vivado -mode batch -source scripts/synthesis/run_shared_pe.tcl
#   vivado -mode batch -source scripts/synthesis/run_baseline.tcl
#   vivado -mode batch -source scripts/synthesis/run_pipelined.tcl
#
# Target : Xilinx Artix-7 xc7a35tcpg236-1, Vivado 2024.2 (manuscript tool version)
# Mode   : in-memory project, synth_design -mode out_of_context, default strategies,
#          clock constraint read BEFORE synthesis (timing-driven synthesis).
# Output : reports/generated/vivado/<design>/   (override with env KYBER_REPORT_DIR)
#
# Every run <name> produces  <name>_util.rpt  <name>_util_hier.rpt  <name>_timing.rpt
# <name>_paths.rpt  <name>_power.rpt  <name>_power.xml  <name>_route_status.rpt
# <name>_clock_util.rpt, and for the 10 ns runs <name>_slacks.txt (2000 worst endpoints).
# ============================================================================
set ::script_dir [file dirname [file normalize [info script]]]
set ::root       [file normalize [file join $::script_dir .. ..]]
cd $::root                                   ;# the RTL's relative $readmemh paths resolve from here
set ::part       "xc7a35tcpg236-1"
if {[info exists ::env(KYBER_REPORT_DIR)]} {
    set ::report_root [file normalize $::env(KYBER_REPORT_DIR)]
} else {
    set ::report_root [file join $::root reports generated vivado]
}

proc kyber_relpath {p} {
    # paths are kept root-relative in report headers so no machine-specific prefix is printed
    set root $::root
    if {[string first $root $p] == 0} { return [string range $p [expr {[string length $root] + 1}] end] }
    return $p
}

proc kyber_sources {design} {
    set common [list rtl/common/mod_reduce_barrett.v rtl/common/mod_addsub.v \
                     rtl/common/mult_conventional.v rtl/common/mult_unit.v rtl/common/zeta_rom.v]
    switch $design {
        shared_pe          { return [concat $common [list rtl/shared_pe/ntt_core_shared.v]] }
        per_phase_baseline { return [concat $common [list rtl/per_phase_baseline/ntt_core_baseline.v]] }
        pipelined_barrett  { return [concat $common \
                                [list rtl/pipelined_barrett/mod_reduce_barrett_pipelined.v \
                                      rtl/pipelined_barrett/mult_conventional_pipelined.v \
                                      rtl/shared_pe/ntt_core_shared.v]] }
        default            { error "unknown design $design" }
    }
}
proc kyber_top {design} {
    expr {$design eq "per_phase_baseline" ? "ntt_core_baseline" : "ntt_core_shared"}
}
proc kyber_defines {design} {
    expr {$design eq "pipelined_barrett" ? [list USE_PIPELINED_BARRETT] : [list]}
}
proc kyber_tag {period} { return "t[string map {. p} [format %.3f $period]]" }

proc kyber_grab {file pattern} {
    if {![file exists $file]} { return "NA" }
    set fh [open $file r]; set data [read $fh]; close $fh
    if {[regexp $pattern $data -> v]} { return [string trim $v] }
    return "NA"
}

# Synthesize + place + route one (design, period) point and write all reports.
#   saif : optional SAIF file for activity-annotated power (see scripts/power/)
# Returns the worst setup slack (WNS) in ns.
proc kyber_impl {design period {tag ""} {with_slacks 0} {saif ""} {saif_strip ""}} {
    set outdir [file join $::report_root $design]
    file mkdir $outdir
    if {$tag eq ""} { set tag [kyber_tag $period] }
    set pfx [file join $outdir $tag]

    create_project -in_memory -part $::part
    read_verilog -sv [kyber_sources $design]
    set_property include_dirs [list rtl/common] [current_fileset]

    if {abs($period - 10.0) < 1e-9} {
        set xdc constraints/clk_10ns.xdc
    } else {
        set xdc [file join $outdir clk_$tag.xdc]
        set fh [open $xdc w]
        puts $fh "create_clock -period [format %.3f $period] -name clk \[get_ports clk\]"
        close $fh
    }
    read_xdc [list [kyber_relpath $xdc]]

    set sargs [list -top [kyber_top $design] -part $::part -mode out_of_context]
    foreach d [kyber_defines $design] { lappend sargs -verilog_define $d }
    eval synth_design $sargs
    opt_design
    place_design
    route_design

    report_utilization                         -file ${pfx}_util.rpt
    report_utilization -hierarchical           -file ${pfx}_util_hier.rpt
    report_timing_summary                      -file ${pfx}_timing.rpt
    report_timing -max_paths 3 -nworst 3 -input_pins -file ${pfx}_paths.rpt
    report_route_status                        -file ${pfx}_route_status.rpt
    report_clock_utilization                   -file ${pfx}_clock_util.rpt
    if {$with_slacks} {
        set fh [open ${pfx}_slacks.txt w]
        foreach p [get_timing_paths -max_paths 2000 -nworst 1 -delay_type max] {
            puts $fh [get_property SLACK $p]
        }
        close $fh
    }
    if {$saif ne ""} { read_saif -strip_path $saif_strip $saif }
    report_power                               -file ${pfx}_power.rpt
    report_power -format xml                   -file ${pfx}_power.xml

    set wns [get_property SLACK [get_timing_paths -delay_type max]]
    puts "##### $design $tag period=[format %.3f $period] WNS=$wns"
    close_project
    return $wns
}

proc kyber_log_closure {design tag period wns} {
    set f [file join $::report_root $design closure_summary.csv]
    set new [expr {![file exists $f]}]
    set fh [open $f a]
    if {$new} { puts $fh "run,period_ns,wns_ns,closed" }
    puts $fh [format "%s,%.3f,%s,%s" $tag $period $wns [expr {$wns >= 0 ? "YES" : "NO"}]]
    close $fh
}

# Relaxation search (shared / per-phase cores, which fail at 10 ns): start at 10 ns and
# set period <- period - WNS + 0.050 until the run meets timing.
proc kyber_closure_relax {design {max_iter 6}} {
    set period 10.000
    for {set i 1} {$i <= $max_iter} {incr i} {
        set tag [kyber_tag $period]
        set wns [kyber_impl $design $period $tag [expr {$i == 1}]]
        kyber_log_closure $design $tag $period $wns
        if {$wns >= 0} { puts "##### $design CLOSES at $period ns"; return $period }
        set period [format "%.3f" [expr {$period - $wns + 0.050}]]
    }
    puts "##### $design did NOT close in $max_iter iterations"
    return 0
}

# Tightening search (pipelined core, which already meets 10 ns): run 10 ns, then step the
# period down from $start in $step ns decrements until a run fails.
proc kyber_closure_tighten {design {start 9.500} {step 0.2} {max_iter 12}} {
    set wns [kyber_impl $design 10.000 [kyber_tag 10.000] 1]
    kyber_log_closure $design [kyber_tag 10.000] 10.000 $wns
    set period $start
    for {set i 1} {$i <= $max_iter} {incr i} {
        set tag [kyber_tag $period]
        set wns [kyber_impl $design $period $tag 0]
        kyber_log_closure $design $tag $period $wns
        if {$wns < 0} { puts "##### $design stops closing at $period ns"; return $period }
        set period [format "%.3f" [expr {$period - $step}]]
    }
    return 0
}

proc kyber_reset_design_dir {design} {
    set d [file join $::report_root $design]
    file mkdir $d
    file delete -force [file join $d closure_summary.csv]
}
