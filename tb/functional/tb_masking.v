`timescale 1ns/1ps
// ============================================================================
// Additive-masking protocol on the UNMODIFIED primary core (ntt_core_shared).
//
//   f = f1 + f2 (mod q),  f1 uniform (data/test_vectors/masking_f1.mem)
//   core(f1,g) + core(f2,g)  (mod q, addition performed here, outside the core)
//       ==  core(f,g)  ==  golden product
//
// Per vector the core is invoked three times: on (f1,g), on (f2,g) and, as the
// unmasked reference, on (f,g). Reports mismatches of the recombined result
// against both the unmasked RTL output and the stored golden product, and the
// latency of a masked product (two invocations).
// +NUM_VEC=<n> (default 256)  +VEC_DIR=<dir>
// ============================================================================
module tb_masking;
    reg clk = 0, rst_n = 0, start = 0, load_a_we = 0, load_b_we = 0;
    reg [7:0]  load_addr = 0, read_addr = 0;
    reg [11:0] load_data = 0;
    wire [11:0] read_data;
    wire done;
    ntt_core_shared dut (.clk(clk), .rst_n(rst_n), .start(start), .done(done),
        .load_a_we(load_a_we), .load_b_we(load_b_we), .load_addr(load_addr),
        .load_data(load_data), .read_addr(read_addr), .read_data(read_data));
    always #5 clk = ~clk;

    integer NUM_VEC;
    reg [8*256-1:0] vec_dir, path;
    reg [11:0] f_all [0:256*256-1], g_all [0:256*256-1], h_all [0:256*256-1], f1_all [0:256*256-1];
    reg [11:0] f2 [0:255], out1 [0:255], out2 [0:255], out0 [0:255];
    integer v, i, cyc, cyc1, cyc2, errs_unmasked, errs_golden, lat_min, lat_max, tot_masked_min, tot_masked_max;
    reg [12:0] sum;

    task reset_core;
        begin rst_n = 0; repeat (3) @(posedge clk); #1; rst_n = 1; @(posedge clk); #1; end
    endtask

    // run the core on (fsrc, g of vector v) and capture the 256 output words in dst
    task run_core(input integer which, input integer vv);
        integer k;
        begin
            reset_core;
            for (k = 0; k < 256; k = k + 1) begin
                load_addr = k; load_a_we = 1;
                load_data = (which == 0) ? f_all[vv*256+k] : (which == 1) ? f1_all[vv*256+k] : f2[k];
                @(posedge clk); #1;
            end
            load_a_we = 0;
            for (k = 0; k < 256; k = k + 1) begin
                load_addr = k; load_data = g_all[vv*256+k]; load_b_we = 1; @(posedge clk); #1;
            end
            load_b_we = 0; @(posedge clk); #1;
            start = 1; @(posedge clk); #1; start = 0;
            cyc = 0;
            while (!done && cyc < 100000) begin @(posedge clk); #1; cyc = cyc + 1; end
            for (k = 0; k < 256; k = k + 1) begin
                read_addr = k; #1;
                if (which == 0) out0[k] = read_data; else if (which == 1) out1[k] = read_data; else out2[k] = read_data;
            end
        end
    endtask

    initial begin
        if (!$value$plusargs("VEC_DIR=%s", vec_dir)) vec_dir = "data/test_vectors";
        if (!$value$plusargs("NUM_VEC=%d", NUM_VEC)) NUM_VEC = 256;
        $sformat(path, "%0s/multi_f.mem", vec_dir);    $readmemh(path, f_all);
        $sformat(path, "%0s/multi_g.mem", vec_dir);    $readmemh(path, g_all);
        $sformat(path, "%0s/multi_h.mem", vec_dir);    $readmemh(path, h_all);
        $sformat(path, "%0s/masking_f1.mem", vec_dir); $readmemh(path, f1_all);
        errs_unmasked = 0; errs_golden = 0; lat_min = 32'h7fffffff; lat_max = 0;
        tot_masked_min = 32'h7fffffff; tot_masked_max = 0;
        repeat (3) @(posedge clk); #1; rst_n = 1; @(posedge clk); #1;
        for (v = 0; v < NUM_VEC; v = v + 1) begin
            for (i = 0; i < 256; i = i + 1) f2[i] = (f_all[v*256+i] + 3329 - f1_all[v*256+i]) % 3329;
            run_core(1, v); cyc1 = cyc;                 // (f1, g)
            run_core(2, v); cyc2 = cyc;                 // (f2, g)
            run_core(0, v);                             // (f,  g)  unmasked reference
            if (cyc1 < lat_min) lat_min = cyc1; if (cyc1 > lat_max) lat_max = cyc1;
            if (cyc2 < lat_min) lat_min = cyc2; if (cyc2 > lat_max) lat_max = cyc2;
            if (cyc1 + cyc2 < tot_masked_min) tot_masked_min = cyc1 + cyc2;
            if (cyc1 + cyc2 > tot_masked_max) tot_masked_max = cyc1 + cyc2;
            for (i = 0; i < 256; i = i + 1) begin
                sum = out1[i] + out2[i];
                if (sum >= 3329) sum = sum - 3329;
                if (sum[11:0] !== out0[i])           errs_unmasked = errs_unmasked + 1;
                if (sum[11:0] !== h_all[v*256+i])    errs_golden   = errs_golden + 1;
            end
        end
        $display("MASKRESULT vectors=%0d invocations=%0d coefficients=%0d mismatches_vs_unmasked_core=%0d mismatches_vs_golden=%0d latency_per_invocation_min=%0d latency_per_invocation_max=%0d masked_latency_min=%0d masked_latency_max=%0d",
                 NUM_VEC, 3*NUM_VEC, NUM_VEC*256, errs_unmasked, errs_golden, lat_min, lat_max, tot_masked_min, tot_masked_max);
        if (errs_unmasked == 0 && errs_golden == 0) $display("MASKING PASS"); else $display("MASKING FAIL");
        $finish;
    end
    initial begin #2000000000; $display("WATCHDOG TIMEOUT"); $finish; end
endmodule
