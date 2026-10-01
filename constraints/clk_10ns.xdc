# Common 10 ns (100 MHz) target used for every area / power / slack comparison in the
# manuscript. The cores are implemented out of context (no I/O buffers): this constrains
# the internal register-to-register timing of the block, which is what Fmax refers to.
# Closure runs at other periods use the same single command with a different -period;
# flow_common.tcl writes those files into reports/generated/vivado/<design>/.
create_clock -period 10.000 -name clk [get_ports clk]
