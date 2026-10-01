`timescale 1ns/1ps
`include "kyber_params.vh"

// Pipelined variant of mult_conventional.v. Identical port list and identical
// arithmetic result; the only difference is that the Barrett reducer's two
// constant multiplies (xM, then tq) are separated by a register (t_B_r)
// instead of forming one combinational chain from prod_r to result. This
// costs one extra cycle per multiply-reduce -- three cycles (S_WAIT, S_EST,
// S_RED) instead of two (S_WAIT, S_REDUCE) -- in exchange for a shorter
// critical path. See mod_reduce_barrett_pipelined.v for the split reducer.
//
// Selected via `+define+USE_PIPELINED_BARRETT in mult_unit.v; every consumer
// FSM (ntt_core_shared.v) waits on `done` and is otherwise unmodified, since
// its wait states are `if (mult_done) ... else <self-loop>`, not a hardcoded
// cycle count.
module mult_conventional_pipelined (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [11:0] a,
    input  wire [11:0] b,
    output reg          done,
    output reg  [11:0] result
);
    localparam S_WAIT = 2'd0, S_EST = 2'd1, S_RED = 2'd2;
    reg  [1:0]  state;
    reg  [23:0] prod_r;
    reg  [12:0] t_B_r;
    wire [12:0] t_B_comb;
    wire [11:0] reduced;

    mod_reduce_barrett_stage1 u_est (.x(prod_r), .t_B(t_B_comb));
    mod_reduce_barrett_stage2 u_red (.x(prod_r), .t_B(t_B_r), .y(reduced));

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state  <= S_WAIT;
            done   <= 1'b0;
            result <= 12'd0;
            prod_r <= 24'd0;
            t_B_r  <= 13'd0;
        end else begin
            case (state)
                S_WAIT: begin
                    done <= 1'b0;
                    if (start) begin
                        prod_r <= a * b;
                        state  <= S_EST;
                    end
                end
                S_EST: begin
                    t_B_r <= t_B_comb;   // uses prod_r registered last cycle
                    state <= S_RED;
                end
                S_RED: begin
                    result <= reduced;   // uses prod_r (held) and t_B_r (just registered)
                    done   <= 1'b1;
                    state  <= S_WAIT;
                end
            endcase
        end
    end
endmodule
