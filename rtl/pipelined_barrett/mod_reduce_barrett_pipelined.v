`timescale 1ns/1ps
`include "kyber_params.vh"

// Two-stage (pipelined) Barrett reduction. The unpipelined reducer
// (mod_reduce_barrett.v) is one combinational block from prod_r to result;
// post-route timing analysis of that block found the critical path running
// through two cascaded, UNREGISTERED DSP48E1 A->P traversals (x*M then t*q),
// each 3.84 ns, accounting for the majority of the path. This variant
// registers the boundary between those two multiplies -- t_B -- so each
// DSP traversal sits in its own pipeline stage instead of one combinational
// chain. Bit-exact identical arithmetic to mod_reduce_barrett.v; the only
// change is where the clock boundary falls. The caller (see
// mult_conventional_pipelined.v) pays one extra clock cycle per
// multiply-reduce for the shorter critical path.
//
// Stage 1: t_B = floor(x*M / 2^K)             -- one DSP48E1 (x*M)
// Stage 2: y   = correct(x - t_B*q)           -- one DSP48E1 (t_B*q) + compare/sub

module mod_reduce_barrett_stage1 (
    input  wire [23:0] x,
    output wire [12:0] t_B
);
    wire [36:0] mul_full = x * `BARRETT_M;
    assign t_B = mul_full[`BARRETT_K +: 13];
endmodule

module mod_reduce_barrett_stage2 (
    input  wire [23:0] x,
    input  wire [12:0] t_B,
    output wire [11:0] y
);
    wire [24:0] r0 = {1'b0, x} - (t_B * `Q);
    wire [24:0] r1 = (r0 >= `Q) ? (r0 - `Q) : r0;

    assign y = r1[11:0];
endmodule
