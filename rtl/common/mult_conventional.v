`timescale 1ns/1ps
`include "kyber_params.vh"

// Baseline modular multiplier: single 12x12 multiply (left to Vivado's
// inference -> DSP48 slice) followed by the shared Barrett reducer.
// 2-cycle latency: cycle 1 registers the raw product, cycle 2 registers
// the reduced result and asserts done.
module mult_conventional (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [11:0] a,
    input  wire [11:0] b,
    output reg         done,
    output reg  [11:0] result
);
    localparam S_WAIT = 1'b0, S_REDUCE = 1'b1;
    reg        state;
    reg [23:0] prod_r;
    wire [11:0] reduced;

    mod_reduce_barrett u_barrett (
        .x(prod_r),
        .y(reduced)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state  <= S_WAIT;
            done   <= 1'b0;
            result <= 12'd0;
            prod_r <= 24'd0;
        end else begin
            case (state)
                S_WAIT: begin
                    done <= 1'b0;
                    if (start) begin
                        prod_r <= a * b;
                        state  <= S_REDUCE;
                    end
                end
                S_REDUCE: begin
                    result <= reduced;
                    done   <= 1'b1;
                    state  <= S_WAIT;
                end
            endcase
        end
    end
endmodule
