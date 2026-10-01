`timescale 1ns/1ps
`include "kyber_params.vh"

// Combinational mod-q add/sub. All intermediates are carried in explicit
// 13-bit width (via concatenation) to avoid silently wrapping in 12-bit
// arithmetic before the correction step is applied.
module mod_add (
    input  wire [11:0] a,
    input  wire [11:0] b,
    output wire [11:0] y
);
    wire [12:0] sum           = {1'b0, a} + {1'b0, b};
    wire [12:0] sum_corrected = (sum >= `Q) ? (sum - `Q) : sum;
    assign y = sum_corrected[11:0];
endmodule

module mod_sub (
    input  wire [11:0] a,
    input  wire [11:0] b,
    output wire [11:0] y
);
    wire [12:0] a_plus_q      = {1'b0, a} + {1'b0, `Q};
    wire [12:0] diff          = a_plus_q - {1'b0, b};
    wire [12:0] diff_corrected = (diff >= `Q) ? (diff - `Q) : diff;
    assign y = diff_corrected[11:0];
endmodule
