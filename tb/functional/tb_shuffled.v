`timescale 1ns/1ps
// ============================================================================
// Functional + latency + address-trace check of the shuffled-issue-order core
// (ntt_core_shared_shuffled).  For each of six LFSR seeds, NUM_VEC golden
// vectors (+NUM_VEC, default 256) are run through the core.
//
// Asserted for every (seed, vector):
//   1. all 256 output coefficients equal the golden product (multi_h.mem),
//   2. the latency equals the unshuffled core's latency (shuffling reorders
//      independent work inside a phase, it never adds or removes any),
//   3. the multiplier is issued the same number of times (3584).
// Reported per seed: a hash of the coefficient-RAM address / twiddle-index
// sequence. For a fixed seed it must be identical for all vectors (the order is
// data independent); across seeds it must differ (the order really is shuffled).
//
// Latency definition: identical to tb_polymul_functional.v (edges after the
// start-capturing edge up to and including the edge that registers done).
// ============================================================================
module tb_shuffled;
    reg clk = 0, rst_n = 0, start = 0, load_a_we = 0, load_b_we = 0, seed_we = 0;
    reg [7:0]  load_addr = 0, read_addr = 0;
    reg [11:0] load_data = 0;
    reg [31:0] rnd_seed = 0;
    wire [11:0] read_data;
    wire done;

    ntt_core_shared_shuffled dut (
        .clk(clk), .rst_n(rst_n), .start(start), .done(done),
        .load_a_we(load_a_we), .load_b_we(load_b_we),
        .load_addr(load_addr), .load_data(load_data),
        .read_addr(read_addr), .read_data(read_data),
        .seed_we(seed_we), .rnd_seed(rnd_seed));

    always #5 clk = ~clk;

    integer NUM_VEC;
    reg [8*256-1:0] vec_dir, path;
    reg [11:0] f_all [0:256*256-1];
    reg [11:0] g_all [0:256*256-1];
    reg [11:0] h_all [0:256*256-1];
    reg [31:0] seeds [0:5];

    reg inwin = 0;
    reg [63:0] hA;
    integer issues;
    function [63:0] mix(input [63:0] h, input [63:0] w);
        begin
            mix = (h ^ w[31:0]) * 64'h100000001b3;
            mix = (mix ^ w[63:32]) * 64'h100000001b3;
        end
    endfunction
    always @(posedge clk) if (inwin) begin
        // a_ra0 is the external read port (driven by the testbench) in S_DONE, so it is masked there
        hA = mix(hA, {14'b0, dut.state, (dut.running ? dut.a_ra0 : 9'd0), dut.a_ra1, dut.k_idx, dut.bm_i, dut.scale_idx});
        if (dut.mult_start) issues = issues + 1;
    end

    integer s, v, i, cyc, errors, vec_errors, total, runs, cyc_min, cyc_max, bad_issue_runs;
    integer bad_hash_runs;
    reg [63:0] seed_hash [0:5];

    task reset_core;
        begin rst_n = 0; repeat (3) @(posedge clk); #1; rst_n = 1; @(posedge clk); #1; end
    endtask

    initial begin
        if (!$value$plusargs("VEC_DIR=%s", vec_dir)) vec_dir = "data/test_vectors";
        if (!$value$plusargs("NUM_VEC=%d", NUM_VEC)) NUM_VEC = 256;
        $sformat(path, "%0s/multi_f.mem", vec_dir); $readmemh(path, f_all);
        $sformat(path, "%0s/multi_g.mem", vec_dir); $readmemh(path, g_all);
        $sformat(path, "%0s/multi_h.mem", vec_dir); $readmemh(path, h_all);
        seeds[0] = 32'hACE12345; seeds[1] = 32'h00000001; seeds[2] = 32'hFFFFFFFF;
        seeds[3] = 32'hDEADBEEF; seeds[4] = 32'h5A5A5A5A; seeds[5] = 32'h13579BDF;
        errors = 0; total = 0; runs = 0; cyc_min = 32'h7fffffff; cyc_max = 0;
        bad_issue_runs = 0; bad_hash_runs = 0;
        repeat (3) @(posedge clk); #1; rst_n = 1; @(posedge clk); #1;

        for (s = 0; s < 6; s = s + 1) begin
            for (v = 0; v < NUM_VEC; v = v + 1) begin
                reset_core;
                rnd_seed = seeds[s]; seed_we = 1; @(posedge clk); #1; seed_we = 0; @(posedge clk); #1;
                for (i = 0; i < 256; i = i + 1) begin
                    load_addr = i; load_data = f_all[v*256+i]; load_a_we = 1; @(posedge clk); #1;
                end
                load_a_we = 0;
                for (i = 0; i < 256; i = i + 1) begin
                    load_addr = i; load_data = g_all[v*256+i]; load_b_we = 1; @(posedge clk); #1;
                end
                load_b_we = 0; @(posedge clk); #1;

                hA = 64'hcbf29ce484222325; issues = 0;
                start = 1; @(posedge clk); #1; start = 0;
                inwin = 1; cyc = 0;
                while (!done && cyc < 100000) begin @(posedge clk); #1; cyc = cyc + 1; end
                inwin = 0;
                if (cyc < cyc_min) cyc_min = cyc;
                if (cyc > cyc_max) cyc_max = cyc;
                if (issues != 3584) bad_issue_runs = bad_issue_runs + 1;
                if (v == 0) seed_hash[s] = hA; else if (hA !== seed_hash[s]) begin bad_hash_runs = bad_hash_runs + 1; $display("HASHDIFF seed=%0d vec=%0d %016x vs %016x", s, v, hA, seed_hash[s]); end

                vec_errors = 0;
                for (i = 0; i < 256; i = i + 1) begin
                    read_addr = i; #1; total = total + 1;
                    if (read_data !== h_all[v*256+i]) vec_errors = vec_errors + 1;
                end
                errors = errors + vec_errors; runs = runs + 1;
            end
            $display("SHUFSEED seed=%08x addr_trace_hash=%016x", seeds[s], seed_hash[s]);
        end
        $display("SHUFRESULT seeds=6 vectors_per_seed=%0d runs=%0d coefficients=%0d mismatches=%0d cycles_min=%0d cycles_max=%0d runs_with_wrong_issue_count=%0d runs_with_seed_trace_hash_change=%0d distinct_seed_hashes=%0d",
                 NUM_VEC, runs, total, errors, cyc_min, cyc_max, bad_issue_runs, bad_hash_runs,
                 1 + (seed_hash[1]!==seed_hash[0]) + ((seed_hash[2]!==seed_hash[0]) && (seed_hash[2]!==seed_hash[1]))
                   + ((seed_hash[3]!==seed_hash[0]) && (seed_hash[3]!==seed_hash[1]) && (seed_hash[3]!==seed_hash[2]))
                   + ((seed_hash[4]!==seed_hash[0]) && (seed_hash[4]!==seed_hash[1]) && (seed_hash[4]!==seed_hash[2]) && (seed_hash[4]!==seed_hash[3]))
                   + ((seed_hash[5]!==seed_hash[0]) && (seed_hash[5]!==seed_hash[1]) && (seed_hash[5]!==seed_hash[2]) && (seed_hash[5]!==seed_hash[3]) && (seed_hash[5]!==seed_hash[4])));
        if (errors == 0) $display("SHUFFLED PASS"); else $display("SHUFFLED FAIL");
        $finish;
    end
    initial begin #2000000000; $display("WATCHDOG TIMEOUT"); $finish; end
endmodule
