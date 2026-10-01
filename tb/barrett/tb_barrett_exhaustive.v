`timescale 1ns/1ps
`include "kyber_params.vh"
// ============================================================================
// Exhaustive check of the Barrett reducers over the COMPLETE 24-bit input
// domain (2^24 = 16,777,216 inputs), against the exact remainder x % 3329.
//
//   dut_c : mod_reduce_barrett                       (primary, combinational)
//   dut_p1/dut_p2 : mod_reduce_barrett_stage1/stage2 (pipelined variant, the two
//                   halves are chained combinationally here; the register between
//                   them in mult_conventional_pipelined.v does not alter values)
//
// The multiplier only ever feeds the reducer with 0 .. (q-1)^2 = 11,075,584,
// which is a strict subset of the range tested here.
// Also records the largest pre-correction remainder r0 seen: a single
// conditional subtraction of q is sufficient iff r0 < 2q for every input.
// ============================================================================
module tb_barrett_exhaustive;
    reg  [23:0] x;
    wire [11:0] y_c, y_p;
    wire [12:0] t_p;

    mod_reduce_barrett        dut_c  (.x(x), .y(y_c));
    mod_reduce_barrett_stage1 dut_p1 (.x(x), .t_B(t_p));
    mod_reduce_barrett_stage2 dut_p2 (.x(x), .t_B(t_p), .y(y_p));

    integer i, mism_c, mism_p, tested;
    integer min_x, max_x, max_r0_c, max_r0_p;
    reg [11:0] exact;

    initial begin
        mism_c = 0; mism_p = 0; tested = 0; max_r0_c = 0; max_r0_p = 0;
        min_x = 32'h7fffffff; max_x = -1;
        for (i = 0; i < 16777216; i = i + 1) begin
            x = i[23:0];
            #1;
            exact = x % 3329;
            if (y_c !== exact) begin
                if (mism_c < 5) $display("MISMATCH primary x=%0d got=%0d expected=%0d", i, y_c, exact);
                mism_c = mism_c + 1;
            end
            if (y_p !== exact) begin
                if (mism_p < 5) $display("MISMATCH pipelined x=%0d got=%0d expected=%0d", i, y_p, exact);
                mism_p = mism_p + 1;
            end
            if (dut_c.r0  > max_r0_c) max_r0_c = dut_c.r0;
            if (dut_p2.r0 > max_r0_p) max_r0_p = dut_p2.r0;
            if (i < min_x) min_x = i;
            if (i > max_x) max_x = i;
            tested = tested + 1;
        end
        $display("BARRETT_RTL reducer=primary   tested=%0d min_input=%0d max_input=%0d mismatches=%0d max_pre_correction_remainder=%0d",
                 tested, min_x, max_x, mism_c, max_r0_c);
        $display("BARRETT_RTL reducer=pipelined tested=%0d min_input=%0d max_input=%0d mismatches=%0d max_pre_correction_remainder=%0d",
                 tested, min_x, max_x, mism_p, max_r0_p);
        $finish;
    end
endmodule
