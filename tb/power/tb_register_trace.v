`timescale 1ns/1ps
// ============================================================================
// Register-level trace dump used to validate the Python cycle-accurate model
// (scripts/tvla/core_model.py) against the RTL.
//
//     -d DUT=ntt_core_shared      (35 register fields: 31 core + 4 multiplier)
//     -d DUT=ntt_core_baseline    (47 register fields: 31 core + 4 x 4 multiplier)
//     +VEC_IDX=<n>  vector to run (default 0)   +OUT=<file>  trace file
//
// One line per clock edge: the value of every modelled register 1 ns AFTER the
// edge. Line 0 is the state after the edge that samples start; the last line is
// the state after the edge that enters S_DONE. Registers that the RTL does not
// reset (memory write address/data) print as 'x' until first written; the
// comparison script treats 'x' as "no value yet".
// Field order == order of Core.regs() in scripts/tvla/core_model.py.
// ============================================================================
`ifndef DUT
 `define DUT ntt_core_shared
`endif
module tb_register_trace;
    reg clk = 0, rst_n = 0, start = 0, load_a_we = 0, load_b_we = 0;
    reg [7:0]  load_addr = 0, read_addr = 0;
    reg [11:0] load_data = 0;
    wire [11:0] read_data;
    wire done;
    `DUT dut (.clk(clk), .rst_n(rst_n), .start(start), .done(done),
        .load_a_we(load_a_we), .load_b_we(load_b_we), .load_addr(load_addr),
        .load_data(load_data), .read_addr(read_addr), .read_data(read_data));
    always #5 clk = ~clk;

    integer VEC_IDX, i, fd, cyc;
    reg [8*256-1:0] vec_dir, out_file, path;
    reg [11:0] f_all [0:256*256-1];
    reg [11:0] g_all [0:256*256-1];

    task dump;
        begin
            $fwrite(fd, "%0h %0h %0h %0h %0h %0h %0h %0h %0h %0h ",
                dut.state, dut.done, dut.target_sel, dut.layer, dut.len_reg, dut.start_reg,
                dut.j_reg, dut.k_idx, dut.bm_i, dut.scale_idx);
            $fwrite(fd, "%0h %0h %0h %0h %0h %0h %0h %0h %0h %0h %0h %0h %0h %0h %0h ",
                dut.mult_op_a, dut.mult_op_b, dut.mult_start, dut.wa, dut.wb, dut.wc, dut.wd,
                dut.w_t, dut.w_sum, dut.w_diff, dut.w_m1, dut.w_za1b1, dut.w_a0b0, dut.w_a0b1, dut.w_a1b0);
            $fwrite(fd, "%0h %0h %0h %0h %0h %0h ",
                dut.mem_a_we, dut.mem_a_wa, dut.mem_a_wd, dut.mem_b_we, dut.mem_b_wa, dut.mem_b_wd);
`ifdef DUT_IS_BASELINE
            $fwrite(fd, "%0h %0h %0h %0h ", dut.u_mult_ntt.u_mult.state, dut.u_mult_ntt.u_mult.prod_r, dut.u_mult_ntt.u_mult.result, dut.u_mult_ntt.u_mult.done);
            $fwrite(fd, "%0h %0h %0h %0h ", dut.u_mult_bm.u_mult.state, dut.u_mult_bm.u_mult.prod_r, dut.u_mult_bm.u_mult.result, dut.u_mult_bm.u_mult.done);
            $fwrite(fd, "%0h %0h %0h %0h ", dut.u_mult_intt.u_mult.state, dut.u_mult_intt.u_mult.prod_r, dut.u_mult_intt.u_mult.result, dut.u_mult_intt.u_mult.done);
            $fwrite(fd, "%0h %0h %0h %0h\n", dut.u_mult_scale.u_mult.state, dut.u_mult_scale.u_mult.prod_r, dut.u_mult_scale.u_mult.result, dut.u_mult_scale.u_mult.done);
`else
            $fwrite(fd, "%0h %0h %0h %0h\n", dut.u_mult.u_mult.state, dut.u_mult.u_mult.prod_r, dut.u_mult.u_mult.result, dut.u_mult.u_mult.done);
`endif
        end
    endtask

    initial begin
        if (!$value$plusargs("VEC_DIR=%s", vec_dir)) vec_dir = "data/test_vectors";
        if (!$value$plusargs("OUT=%s", out_file))    out_file = "register_trace.txt";
        if (!$value$plusargs("VEC_IDX=%d", VEC_IDX)) VEC_IDX = 0;
        $sformat(path, "%0s/multi_f.mem", vec_dir); $readmemh(path, f_all);
        $sformat(path, "%0s/multi_g.mem", vec_dir); $readmemh(path, g_all);
        fd = $fopen(out_file, "w");
        repeat (3) @(posedge clk); #1; rst_n = 1; @(posedge clk); #1;
        for (i = 0; i < 256; i = i + 1) begin
            load_addr = i; load_data = f_all[VEC_IDX*256+i]; load_a_we = 1; @(posedge clk); #1;
        end
        load_a_we = 0;
        for (i = 0; i < 256; i = i + 1) begin
            load_addr = i; load_data = g_all[VEC_IDX*256+i]; load_b_we = 1; @(posedge clk); #1;
        end
        load_b_we = 0; @(posedge clk); #1;
        start = 1; @(posedge clk); #1; start = 0;
        dump;                                   // after the start-capturing edge
        cyc = 0;
        while (dut.state != 6'd37 && cyc < 100000) begin @(posedge clk); #1; cyc = cyc + 1; dump; end
        $fclose(fd);
        $display("TRACE_DONE lines=%0d", cyc + 1);
        $finish;
    end
endmodule
