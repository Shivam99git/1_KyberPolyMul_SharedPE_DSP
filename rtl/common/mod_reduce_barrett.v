`timescale 1ns/1ps
`include "kyber_params.vh"

// Reduces a 24-bit product (0 .. (Q-1)^2) to the range [0, Q) using Barrett
// reduction. Constants BARRETT_K / BARRETT_M / BARRETT_MAX_EXTRA_SUB were
// derived and are verified over the FULL 24-bit input range by
// scripts/verification/barrett_exhaustive.py (software model) and
// tb/barrett/tb_barrett_exhaustive.v (this RTL, 2^24 inputs).
// Used by mult_conventional.v (primary core). The pipelined-Barrett core splits
// the same arithmetic in rtl/pipelined_barrett/mod_reduce_barrett_pipelined.v.
module mod_reduce_barrett (
    input  wire [23:0] x,
    output wire [11:0] y
);
    wire [36:0] mul_full = x * `BARRETT_M;
    wire [12:0] t        = mul_full[`BARRETT_K +: 13];
    wire [24:0] r0       = {1'b0, x} - (t * `Q);
    wire [24:0] r1       = (r0 >= `Q) ? (r0 - `Q) : r0;

    assign y = r1[11:0];
endmodule
