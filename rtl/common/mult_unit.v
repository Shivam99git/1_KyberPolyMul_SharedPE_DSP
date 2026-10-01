`timescale 1ns/1ps

// Single switch point: every consumer (butterflies, base multiplication,
// top-level core) instantiates this wrapper instead of a concrete
// multiplier, so the primary-vs-pipelined-Barrett comparison is a one-line
// `+define+USE_PIPELINED_BARRETT` recompile rather than two divergent
// codebases. (The CORDIC and systolic multiplier branches of the original
// research tree are not part of this release.)
module mult_unit (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [11:0] a,
    input  wire [11:0] b,
    output wire        done,
    output wire [11:0] result
);
`ifdef USE_PIPELINED_BARRETT
    mult_conventional_pipelined u_mult (.clk(clk), .rst_n(rst_n), .start(start), .a(a), .b(b), .done(done), .result(result));
`else
    mult_conventional  u_mult (.clk(clk), .rst_n(rst_n), .start(start), .a(a), .b(b), .done(done), .result(result));
`endif
endmodule
