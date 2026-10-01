`timescale 1ns/1ps
// ============================================================================
// Functional + cycle-count testbench for the Kyber polynomial-multiplier cores.
//
// Selects the device under test at elaboration time:
//     -d DUT=ntt_core_shared            primary shared-PE core (default)
//     -d DUT=ntt_core_baseline          per-phase reference core
//     -d DUT=ntt_core_shared -d USE_PIPELINED_BARRETT
//                                       pipelined-Barrett shared-PE core
//
// Run-time plusargs (all optional):
//     +VEC_DIR=<dir>   directory holding multi_f/g/h.mem   (default data/test_vectors)
//     +OUT=<file>      where to write the RTL output words (default rtl_out.mem)
//     +NUM_VEC=<n>     number of vectors to run             (default 256)
//
// What is measured
//   * Every output coefficient is compared with multi_h.mem (mismatch count).
//     The RTL words are ALSO written to +OUT so that
//     scripts/verification/run_reference_tests.py can re-check them against a
//     schoolbook product recomputed from f and g (no dependence on multi_h.mem).
//   * Latency = number of clock edges after the edge that samples start=1, up
//     to and including the edge at which `done` is registered high. This equals
//     the closed-form N_cyc of the manuscript (Eq. 3): the FSM spends one clock
//     in each of S_NTT_INIT ... S_DONE and S_IDLE is not counted.
//   * For vector 0 the latency is split by FSM phase using the state register
//     (hierarchical reference dut.state) and the multiplier-issue pulses
//     (dut.mult_start) are counted.
// All stimulus is driven 1 ns after a clock edge, so there is no start-edge race.
// ============================================================================
`ifndef DUT
 `define DUT ntt_core_shared
`endif

module tb_polymul_functional;
    reg clk = 0, rst_n = 0, start = 0;
    reg load_a_we = 0, load_b_we = 0;
    reg [7:0]  load_addr = 0;
    reg [11:0] load_data = 0;
    reg [7:0]  read_addr = 0;
    wire [11:0] read_data;
    wire done;

    `DUT dut (
        .clk(clk), .rst_n(rst_n), .start(start), .done(done),
        .load_a_we(load_a_we), .load_b_we(load_b_we),
        .load_addr(load_addr), .load_data(load_data),
        .read_addr(read_addr), .read_data(read_data)
    );

    always #5 clk = ~clk;

    integer NUM_VEC;
    reg [8*256-1:0] vec_dir, out_file, path;
    reg [11:0] f_all [0:256*256-1];
    reg [11:0] g_all [0:256*256-1];
    reg [11:0] h_all [0:256*256-1];

    integer v, i, fd, errors, vec_errors, total, cyc, cyc_min, cyc_max, first_cyc;
    integer unique_lat;

    // ---- per-phase profile, collected only while `profile` is high ----
    reg profile = 0;
    integer c_fwd, c_pwm, c_inv, c_scl, c_ctl, issues;
    always @(posedge clk) if (profile) begin
        case (dut.state)
            6'd1, 6'd8, 6'd23, 6'd31, 6'd37: c_ctl = c_ctl + 1; // *_INIT states, S_DONE
            6'd2, 6'd3, 6'd4, 6'd5, 6'd6, 6'd7:                   c_fwd = c_fwd + 1;
            6'd9,  6'd10, 6'd11, 6'd12, 6'd13, 6'd14, 6'd15, 6'd16,
            6'd17, 6'd18, 6'd19, 6'd20, 6'd21, 6'd22:             c_pwm = c_pwm + 1;
            6'd24, 6'd25, 6'd26, 6'd27, 6'd28, 6'd29, 6'd30:      c_inv = c_inv + 1;
            6'd32, 6'd33, 6'd34, 6'd35, 6'd36:                    c_scl = c_scl + 1;
            default: ;
        endcase
        if (dut.mult_start) issues = issues + 1;
    end

    task reset_core;
        begin
            rst_n = 0; repeat (3) @(posedge clk); #1; rst_n = 1; @(posedge clk); #1;
        end
    endtask

    initial begin
        if (!$value$plusargs("VEC_DIR=%s", vec_dir)) vec_dir = "data/test_vectors";
        if (!$value$plusargs("OUT=%s", out_file))    out_file = "rtl_out.mem";
        if (!$value$plusargs("NUM_VEC=%d", NUM_VEC)) NUM_VEC = 256;
        errors = 0; total = 0; cyc_min = 32'h7fffffff; cyc_max = 0; first_cyc = 0;
        c_fwd = 0; c_pwm = 0; c_inv = 0; c_scl = 0; c_ctl = 0; issues = 0;

        $sformat(path, "%0s/multi_f.mem", vec_dir); $readmemh(path, f_all);
        $sformat(path, "%0s/multi_g.mem", vec_dir); $readmemh(path, g_all);
        $sformat(path, "%0s/multi_h.mem", vec_dir); $readmemh(path, h_all);
        fd = $fopen(out_file, "w");

        repeat (3) @(posedge clk); #1; rst_n = 1; @(posedge clk); #1;

        for (v = 0; v < NUM_VEC; v = v + 1) begin
            reset_core;
            for (i = 0; i < 256; i = i + 1) begin
                load_addr = i; load_data = f_all[v*256+i]; load_a_we = 1; @(posedge clk); #1;
            end
            load_a_we = 0;
            for (i = 0; i < 256; i = i + 1) begin
                load_addr = i; load_data = g_all[v*256+i]; load_b_we = 1; @(posedge clk); #1;
            end
            load_b_we = 0; @(posedge clk); #1;

            // one-cycle start pulse; the core samples it at the next edge (P0)
            start = 1; @(posedge clk); #1; start = 0;
            cyc = 0;
            if (v == 0) profile = 1;
            while (!done && cyc < 100000) begin
                @(posedge clk); #1; cyc = cyc + 1;
            end
            profile = 0;
            if (cyc >= 100000) begin
                $display("TIMEOUT vector %0d", v); $finish;
            end
            if (v == 0) first_cyc = cyc;
            if (cyc < cyc_min) cyc_min = cyc;
            if (cyc > cyc_max) cyc_max = cyc;

            vec_errors = 0;
            for (i = 0; i < 256; i = i + 1) begin
                read_addr = i; #1;
                $fdisplay(fd, "%03x", read_data);
                total = total + 1;
                if (read_data !== h_all[v*256+i]) begin
                    if (vec_errors < 3)
                        $display("MISMATCH vec=%0d coeff=%0d expected=%0d got=%0d", v, i, h_all[v*256+i], read_data);
                    vec_errors = vec_errors + 1; errors = errors + 1;
                end
            end
        end
        $fclose(fd);

        // The profile window excludes the start edge, so the phase counters
        // add up to the latency of vector 0.
        $display("PROFILE vector0 fwd_ntt=%0d pwm=%0d inv_ntt=%0d scaling=%0d init_done=%0d sum=%0d mult_issues=%0d",
                 c_fwd, c_pwm, c_inv, c_scl, c_ctl, c_fwd+c_pwm+c_inv+c_scl+c_ctl, issues);
        $display("RESULT design=%0s vectors=%0d coefficients=%0d mismatches=%0d cycles_first=%0d cycles_min=%0d cycles_max=%0d",
                 `"`DUT`", NUM_VEC, total, errors, first_cyc, cyc_min, cyc_max);
        if (errors == 0) $display("FUNCTIONAL PASS"); else $display("FUNCTIONAL FAIL");
        $finish;
    end

    initial begin #2000000000; $display("WATCHDOG TIMEOUT"); $finish; end
endmodule
