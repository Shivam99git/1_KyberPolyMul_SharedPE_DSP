`timescale 1ns/1ps
`include "kyber_params.vh"

// The ROM image locations are overridable macros so the same RTL elaborates
// from any working directory. Default: relative to the repository root.
// Every flow in this repository passes absolute paths via
// +define+ZETA_NTT_MEM / +define+ZETA_BM_MEM (xvlog -d / synth_design -verilog_define).
`ifndef ZETA_NTT_MEM
 `define ZETA_NTT_MEM "data/test_vectors/zetas_ntt.mem"
`endif
`ifndef ZETA_BM_MEM
 `define ZETA_BM_MEM "data/test_vectors/zetas_basemul.mem"
`endif

// zetas_ntt.mem holds ZETA_NTT[k] for k=1..127 at 0-based index (k-1);
// zetas_basemul.mem holds ZETA_BASEMUL[i] for i=0..127. Single shared ROM,
// two async read ports (NTT/INTT twiddle vs base-mul twiddle).
module zeta_rom (
    input  wire [6:0] ntt_addr,
    output wire [11:0] ntt_zeta,
    input  wire [6:0] bm_addr,
    output wire [11:0] bm_zeta
);
    reg [11:0] rom_ntt [0:126];
    reg [11:0] rom_bm  [0:127];

    initial begin
        $readmemh(`ZETA_NTT_MEM, rom_ntt);
        $readmemh(`ZETA_BM_MEM,  rom_bm);
    end

    assign ntt_zeta = rom_ntt[ntt_addr];
    assign bm_zeta  = rom_bm[bm_addr];
endmodule
