`timescale 1ns/1ps
// ============================================================================
// Control-flow / memory-address invariance experiment (simulation only).
//
// Claim under test: for every evaluated input pair, the core
//   (A) takes the same number of clock cycles from start to done,
//   (B) follows the same cycle-by-cycle control trajectory, and
//   (C) issues the same cycle-by-cycle memory-address sequence.
//
// Selected DUT (same switches as tb_polymul_functional.v):
//     -d DUT=ntt_core_shared | ntt_core_baseline | ntt_core_shared_shuffled
//     -d USE_PIPELINED_BARRETT   (selects the pipelined-Barrett multiplier)
//
// Window: the clock edges after the start-capturing edge up to and including
// the edge that registers `done` (identical to the latency definition used by
// tb_polymul_functional.v). Operand loading is outside the window.
//
// Fingerprints, sampled at every clock edge inside the window:
//   B  control word : FSM state, target_sel, layer, len_reg, start_reg, j_reg,
//                     k_idx, bm_i, scale_idx, mult_start, mult_done (the
//                     start/done handshake with the multiplier), done
//   C  address word: both coefficient-RAM read-address pairs (a_ra0, a_ra1,
//                     b_ra0, b_ra1; a_ra0 is the testbench-driven external read
//                     port in S_DONE and is masked there), both write-enables and write addresses
//                     (write address masked to 0 when its write-enable is low:
//                     those registers are outside the reset block and carry a
//                     don't-care value when no write occurs)
//   D  data word   : wa, wb, w_t, mem_a_wd, mem_b_wd. NEGATIVE CONTROL ONLY.
//                     These registers carry coefficients, so D must differ
//                     between inputs; if it did not, the harness would be unable
//                     to see data-dependent behaviour at all.
//
// Vector 0 is recorded as the reference; every other vector is compared with it
// live, cycle by cycle (mismatch counters), and a 64-bit FNV-style hash of each
// stream is printed for the Python report.
//
// Scope: this is an RTL-level, zero-delay control-flow experiment. Combinational
// glitches, routing capacitance and physical measurement effects are outside it.
// ============================================================================
`ifndef DUT
 `define DUT ntt_core_shared
`endif
`define MAXCYC 40000

module tb_constant_time;
    reg clk = 0, rst_n = 0, start = 0, load_a_we = 0, load_b_we = 0;
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
`ifdef SHUFFLED_DUT
        , .seed_we(seed_we), .rnd_seed(rnd_seed)
`endif
    );
`ifdef SHUFFLED_DUT
    reg seed_we = 0; reg [31:0] rnd_seed = 32'hACE12345;
`endif

    always #5 clk = ~clk;

    integer NUM_VEC;
    reg [8*256-1:0] vec_dir, path;
    reg [11:0] f_all [0:256*256-1];
    reg [11:0] g_all [0:256*256-1];

    // ---- per-cycle fingerprints ----
    wire [63:0] wordB = {2'b0,
        dut.state, dut.target_sel, dut.layer, dut.len_reg, dut.start_reg,
        dut.j_reg, dut.k_idx, dut.bm_i, dut.scale_idx,
        dut.mult_start, dut.mult_done, dut.done};
    wire [63:0] wordC = {8'b0,
        (dut.running ? dut.a_ra0 : 9'd0), dut.a_ra1, dut.b_ra0, dut.b_ra1,
        dut.mem_a_we, (dut.mem_a_we ? dut.mem_a_wa : 9'd0),
        dut.mem_b_we, (dut.mem_b_we ? dut.mem_b_wa : 9'd0)};
    wire [63:0] wordD = {4'b0, dut.wa, dut.wb, dut.w_t,
        (dut.mem_a_we ? dut.mem_a_wd : 12'd0), (dut.mem_b_we ? dut.mem_b_wd : 12'd0)};

    reg [63:0] refB [0:`MAXCYC-1];
    reg [63:0] refC [0:`MAXCYC-1];
    integer ref_len;

    reg recording = 0, comparing = 0;
    reg [63:0] hB, hC, hD;
    integer cyc_w, mmB, mmC, v, i, cyc, len_mismatch_vecs;
    integer ctrl_bad_vecs, addr_bad_vecs;
    reg [63:0] hB0, hC0;

    function [63:0] mix(input [63:0] h, input [63:0] w);
        begin
            mix = (h ^ w[31:0]) * 64'h100000001b3;
            mix = (mix ^ w[63:32]) * 64'h100000001b3;
        end
    endfunction

    // sample inside the window
    reg inwin = 0;
    always @(posedge clk) if (inwin) begin
        hB = mix(hB, wordB); hC = mix(hC, wordC); hD = mix(hD, wordD);
        if (recording) begin
            if (cyc_w < `MAXCYC) begin refB[cyc_w] = wordB; refC[cyc_w] = wordC; end
        end else if (comparing && cyc_w < ref_len) begin
            if (wordB !== refB[cyc_w]) mmB = mmB + 1;
            if (wordC !== refC[cyc_w]) mmC = mmC + 1;
        end
        cyc_w = cyc_w + 1;
    end

    task reset_core;
        begin rst_n = 0; repeat (3) @(posedge clk); #1; rst_n = 1; @(posedge clk); #1; end
    endtask

    integer hDcount, distinctD;
    reg [63:0] hD_first;

    initial begin
        if (!$value$plusargs("VEC_DIR=%s", vec_dir)) vec_dir = "data/test_vectors";
        if (!$value$plusargs("NUM_VEC=%d", NUM_VEC)) NUM_VEC = 256;
        $sformat(path, "%0s/multi_f.mem", vec_dir); $readmemh(path, f_all);
        $sformat(path, "%0s/multi_g.mem", vec_dir); $readmemh(path, g_all);
        ref_len = 0; len_mismatch_vecs = 0; ctrl_bad_vecs = 0; addr_bad_vecs = 0; distinctD = 0;
        repeat (3) @(posedge clk); #1; rst_n = 1; @(posedge clk); #1;

        for (v = 0; v < NUM_VEC; v = v + 1) begin
            reset_core;
`ifdef SHUFFLED_DUT
            seed_we = 1; rnd_seed = 32'hACE12345; @(posedge clk); #1; seed_we = 0; @(posedge clk); #1;
`endif
            for (i = 0; i < 256; i = i + 1) begin
                load_addr = i; load_data = f_all[v*256+i]; load_a_we = 1; @(posedge clk); #1;
            end
            load_a_we = 0;
            for (i = 0; i < 256; i = i + 1) begin
                load_addr = i; load_data = g_all[v*256+i]; load_b_we = 1; @(posedge clk); #1;
            end
            load_b_we = 0; @(posedge clk); #1;

            hB = 64'hcbf29ce484222325; hC = 64'hcbf29ce484222325; hD = 64'hcbf29ce484222325;
            cyc_w = 0; mmB = 0; mmC = 0;
            recording = (v == 0); comparing = (v != 0);
            start = 1; @(posedge clk); #1; start = 0;
            inwin = 1; cyc = 0;
            while (!done && cyc < `MAXCYC) begin @(posedge clk); #1; cyc = cyc + 1; end
            inwin = 0; recording = 0; comparing = 0;

            if (v == 0) begin ref_len = cyc; hB0 = hB; hC0 = hC; hD_first = hD; end
            else begin
                if (cyc != ref_len) len_mismatch_vecs = len_mismatch_vecs + 1;
                if (mmB != 0 || hB !== hB0) ctrl_bad_vecs = ctrl_bad_vecs + 1;
                if (mmC != 0 || hC !== hC0) addr_bad_vecs = addr_bad_vecs + 1;
                if (hD !== hD_first) distinctD = distinctD + 1;
            end
            $display("CTVEC vec=%0d len=%0d hashB=%016x hashC=%016x hashD=%016x mmB=%0d mmC=%0d",
                     v, cyc, hB, hC, hD, mmB, mmC);
        end
        $display("CTRESULT design=%0s vectors=%0d ref_len=%0d len_mismatch_vectors=%0d control_mismatch_vectors=%0d address_mismatch_vectors=%0d data_register_differs_in=%0d",
                 `"`DUT`", NUM_VEC, ref_len, len_mismatch_vecs, ctrl_bad_vecs, addr_bad_vecs, distinctD);
        $finish;
    end

    initial begin #2000000000; $display("WATCHDOG TIMEOUT"); $finish; end
endmodule
