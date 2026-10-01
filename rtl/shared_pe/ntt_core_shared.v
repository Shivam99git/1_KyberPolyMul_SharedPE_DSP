`timescale 1ns/1ps
`include "kyber_params.vh"

// ============================================================================
// Resource-shared NTT-based polynomial multiplier for CRYSTALS-Kyber / ML-KEM
//   h = INTT( NTT(f) o NTT(g) )  over Z_3329[x]/(x^256+1)
//
// OPTIMISATION vs. the baseline serial core:
//   The baseline instantiated FOUR mult_unit blocks (one buried inside the CT
//   butterfly, one inside the GS butterfly, one inside base-mul, one for the
//   final N_INV scaling) plus SIX mod_add/mod_sub instances. Because the four
//   algorithm phases (forward NTT -> base-mul -> inverse NTT -> scaling) run
//   strictly sequentially in time, at most one of those multipliers is ever
//   active at once, so three of them were pure duplicated area.
//
//   This core keeps EXACTLY ONE shared multiplier (mult_unit -> one DSP +
//   one Barrett reducer), ONE shared modular adder, and ONE shared modular
//   subtractor. Every phase time-multiplexes those single units through
//   operand muxes driven by the control FSM. Since nothing ran in parallel
//   before, this removes the duplicated arithmetic at ZERO latency penalty
//   (a couple of extra micro-steps per operation, but the same throughput
//   ceiling of one butterfly at a time).
//
//   The elementary multiplier is selected in mult_unit: conventional
//   two-cycle multiply-reduce by default, or the pipelined-Barrett variant
//   (three-cycle multiply-reduce) with `+define+USE_PIPELINED_BARRETT.
//
// Memories: mem_a / mem_b, each 256x12, single write port + 2 async read
// ports (efficiently inferable as distributed RAM).
// ============================================================================
module ntt_core_shared (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    output reg         done,

    input  wire        load_a_we,
    input  wire        load_b_we,
    input  wire [7:0]  load_addr,
    input  wire [11:0] load_data,

    input  wire [7:0]  read_addr,
    output wire [11:0] read_data
);
    reg [11:0] mem_a [0:255];
    reg [11:0] mem_b [0:255];

    // ---------------- state encoding ----------------
    localparam S_IDLE       = 6'd0,
               // forward NTT (Cooley-Tukey), run twice (mem_a then mem_b)
               S_NTT_INIT   = 6'd1,
               S_NTT_LOAD   = 6'd2,
               S_NTT_MUL    = 6'd3,
               S_NTT_MULW   = 6'd4,
               S_NTT_WB0    = 6'd5,
               S_NTT_WB1    = 6'd6,
               S_NTT_ADV    = 6'd7,
               // base multiplication (pointwise, degree-2)
               S_BM_INIT    = 6'd8,
               S_BM_LOAD    = 6'd9,
               S_BM_M1      = 6'd10,   // a1*b1
               S_BM_M1W     = 6'd11,
               S_BM_M2      = 6'd12,   // zeta*(a1*b1)
               S_BM_M2W     = 6'd13,
               S_BM_M3      = 6'd14,   // a0*b0
               S_BM_M3W     = 6'd15,
               S_BM_WB0     = 6'd16,   // c0 = a0*b0 + zeta*a1*b1
               S_BM_M4      = 6'd17,   // a0*b1
               S_BM_M4W     = 6'd18,
               S_BM_M5      = 6'd19,   // a1*b0
               S_BM_M5W     = 6'd20,
               S_BM_WB1     = 6'd21,   // c1 = a0*b1 + a1*b0
               S_BM_ADV     = 6'd22,
               // inverse NTT (Gentleman-Sande)
               S_INTT_INIT  = 6'd23,
               S_INTT_LOAD  = 6'd24,
               S_INTT_SUM   = 6'd25,   // sum=a+b, diff=b-a
               S_INTT_MUL   = 6'd26,   // zeta*diff
               S_INTT_MULW  = 6'd27,
               S_INTT_WB0   = 6'd28,
               S_INTT_WB1   = 6'd29,
               S_INTT_ADV   = 6'd30,
               // final scaling by N_INV = 128^-1 mod q
               S_SCALE_INIT = 6'd31,
               S_SCALE_LOAD = 6'd32,
               S_SCALE_MUL  = 6'd33,
               S_SCALE_MULW = 6'd34,
               S_SCALE_WB   = 6'd35,
               S_SCALE_ADV  = 6'd36,
               S_DONE       = 6'd37;

    reg [5:0] state;

    // ---------------- iteration / control registers ----------------
    reg       target_sel;     // 0 = forward NTT over mem_a, 1 = over mem_b
    reg [2:0] layer;
    reg [8:0] len_reg;
    reg [8:0] start_reg;
    reg [8:0] j_reg;
    reg [6:0] k_idx;
    reg [6:0] bm_i;
    reg [8:0] scale_idx;

    // ---------------- working registers ----------------
    reg [11:0] wa, wb, wc, wd;      // butterfly / base-mul operands
    reg [11:0] w_t;                 // latest multiply result
    reg [11:0] w_sum;               // GS sum
    reg [11:0] w_diff;              // GS difference
    reg [11:0] w_m1, w_za1b1, w_a0b0, w_a0b1, w_a1b0; // base-mul temporaries

    // ---------------- shared multiplier ----------------
    reg  [11:0] mult_op_a, mult_op_b;
    reg         mult_start;
    wire        mult_done;
    wire [11:0] mult_res;
    wire [11:0] zrom_ntt_zeta, zrom_bm_zeta;

    mult_unit u_mult (
        .clk(clk), .rst_n(rst_n),
        .start(mult_start), .a(mult_op_a), .b(mult_op_b),
        .done(mult_done), .result(mult_res)
    );

    zeta_rom u_zrom (
        .ntt_addr(k_idx), .ntt_zeta(zrom_ntt_zeta),
        .bm_addr(bm_i),   .bm_zeta(zrom_bm_zeta)
    );

    // ---------------- shared modular add / sub (operand muxes) ----------------
    reg  [11:0] add_a, add_b, sub_a, sub_b;
    wire [11:0] add_y, sub_y;

    mod_add u_add (.a(add_a), .b(add_b), .y(add_y));
    mod_sub u_sub (.a(sub_a), .b(sub_b), .y(sub_y));

    always @(*) begin
        // default
        add_a = wa; add_b = w_t;
        case (state)
            S_NTT_WB0 : begin add_a = wa;     add_b = w_t;      end // a + zeta*b
            S_INTT_SUM: begin add_a = wa;     add_b = wb;       end // a + b
            S_BM_WB0  : begin add_a = w_a0b0; add_b = w_za1b1;  end // c0
            S_BM_WB1  : begin add_a = w_a0b1; add_b = w_a1b0;   end // c1
            default   : begin add_a = wa;     add_b = w_t;      end
        endcase
    end

    always @(*) begin
        sub_a = wa; sub_b = w_t;
        case (state)
            S_NTT_WB1 : begin sub_a = wa; sub_b = w_t; end // a - zeta*b
            S_INTT_SUM: begin sub_a = wb; sub_b = wa; end // b - a
            default   : begin sub_a = wa; sub_b = w_t; end
        endcase
    end

    // ---------------- memory read ports (async) ----------------
    wire running   = (state != S_IDLE) && (state != S_DONE);
    wire in_bm     = (state >= S_BM_INIT)    && (state <= S_BM_ADV);
    wire in_scale  = (state >= S_SCALE_INIT) && (state <= S_SCALE_ADV);

    wire [8:0] a_ra0 = !running ? {1'b0, read_addr} :
                        in_bm    ? {bm_i, 1'b0} :
                        in_scale ? scale_idx :
                                   j_reg;
    wire [8:0] a_ra1 = in_bm ? {bm_i, 1'b1} : (j_reg + len_reg);
    wire [11:0] a_rd0 = mem_a[a_ra0];
    wire [11:0] a_rd1 = mem_a[a_ra1];
    assign read_data = a_rd0;

    wire [8:0] b_ra0 = in_bm ? {bm_i, 1'b0} : j_reg;
    wire [8:0] b_ra1 = in_bm ? {bm_i, 1'b1} : (j_reg + len_reg);
    wire [11:0] b_rd0 = mem_b[b_ra0];
    wire [11:0] b_rd1 = mem_b[b_ra1];

    // ---------------- memory write ports (single each, load muxed in) ----------------
    reg        mem_a_we; reg [8:0] mem_a_wa; reg [11:0] mem_a_wd;
    reg        mem_b_we; reg [8:0] mem_b_wa; reg [11:0] mem_b_wd;

    wire        final_a_we = mem_a_we | load_a_we;
    wire [8:0]  final_a_wa = load_a_we ? {1'b0, load_addr} : mem_a_wa;
    wire [11:0] final_a_wd = load_a_we ? load_data : mem_a_wd;
    wire        final_b_we = mem_b_we | load_b_we;
    wire [8:0]  final_b_wa = load_b_we ? {1'b0, load_addr} : mem_b_wa;
    wire [11:0] final_b_wd = load_b_we ? load_data : mem_b_wd;

    always @(posedge clk) begin
        if (final_a_we) mem_a[final_a_wa] <= final_a_wd;
        if (final_b_we) mem_b[final_b_wa] <= final_b_wd;
    end

    // ---------------- control FSM ----------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; done <= 1'b0; target_sel <= 1'b0;
            layer <= 3'd0; len_reg <= 9'd0; start_reg <= 9'd0; j_reg <= 9'd0;
            k_idx <= 7'd0; bm_i <= 7'd0; scale_idx <= 9'd0;
            mult_op_a <= 12'd0; mult_op_b <= 12'd0;
            wa <= 12'd0; wb <= 12'd0; wc <= 12'd0; wd <= 12'd0;
            w_t <= 12'd0; w_sum <= 12'd0; w_diff <= 12'd0;
            w_m1 <= 12'd0; w_za1b1 <= 12'd0; w_a0b0 <= 12'd0; w_a0b1 <= 12'd0; w_a1b0 <= 12'd0;
        end else begin
            // one-shot / default-low strobes
            mult_start <= 1'b0;
            mem_a_we <= 1'b0; mem_b_we <= 1'b0;

            case (state)
                S_IDLE: begin
                    done <= 1'b0;
                    if (start) begin target_sel <= 1'b0; state <= S_NTT_INIT; end
                end

                // ---------------- forward NTT ----------------
                S_NTT_INIT: begin
                    layer <= 3'd0; len_reg <= 9'd128; start_reg <= 9'd0; j_reg <= 9'd0;
                    k_idx <= 7'd0;
                    state <= S_NTT_LOAD;
                end
                S_NTT_LOAD: begin
                    if (!target_sel) begin wa <= a_rd0; wb <= a_rd1; end
                    else             begin wa <= b_rd0; wb <= b_rd1; end
                    state <= S_NTT_MUL;
                end
                S_NTT_MUL: begin
                    mult_op_a <= zrom_ntt_zeta; mult_op_b <= wb; mult_start <= 1'b1;
                    state <= S_NTT_MULW;
                end
                S_NTT_MULW: if (mult_done) begin w_t <= mult_res; state <= S_NTT_WB0; end
                S_NTT_WB0: begin
                    if (!target_sel) begin mem_a_we <= 1'b1; mem_a_wa <= j_reg; mem_a_wd <= add_y; end
                    else             begin mem_b_we <= 1'b1; mem_b_wa <= j_reg; mem_b_wd <= add_y; end
                    state <= S_NTT_WB1;
                end
                S_NTT_WB1: begin
                    if (!target_sel) begin mem_a_we <= 1'b1; mem_a_wa <= j_reg + len_reg; mem_a_wd <= sub_y; end
                    else             begin mem_b_we <= 1'b1; mem_b_wa <= j_reg + len_reg; mem_b_wd <= sub_y; end
                    state <= S_NTT_ADV;
                end
                S_NTT_ADV: begin
                    if (j_reg + 9'd1 != start_reg + len_reg) begin
                        j_reg <= j_reg + 9'd1;
                        state <= S_NTT_LOAD;
                    end else if (start_reg + (len_reg << 1) >= 9'd256) begin
                        if (layer == 3'd6) begin
                            if (!target_sel) begin
                                target_sel <= 1'b1;
                                layer <= 3'd0; len_reg <= 9'd128; start_reg <= 9'd0; j_reg <= 9'd0;
                                k_idx <= 7'd0;
                                state <= S_NTT_LOAD;
                            end else begin
                                bm_i <= 7'd0;
                                state <= S_BM_INIT;
                            end
                        end else begin
                            layer <= layer + 3'd1; len_reg <= len_reg >> 1;
                            start_reg <= 9'd0; j_reg <= 9'd0; k_idx <= k_idx + 7'd1;
                            state <= S_NTT_LOAD;
                        end
                    end else begin
                        start_reg <= start_reg + (len_reg << 1);
                        j_reg     <= start_reg + (len_reg << 1);
                        k_idx     <= k_idx + 7'd1;
                        state <= S_NTT_LOAD;
                    end
                end

                // ---------------- base multiplication ----------------
                S_BM_INIT: begin bm_i <= 7'd0; state <= S_BM_LOAD; end
                S_BM_LOAD: begin
                    wa <= a_rd0; wb <= a_rd1; wc <= b_rd0; wd <= b_rd1; // a0,a1,b0,b1
                    state <= S_BM_M1;
                end
                S_BM_M1:  begin mult_op_a <= wb; mult_op_b <= wd; mult_start <= 1'b1; state <= S_BM_M1W; end
                S_BM_M1W: if (mult_done) begin w_m1 <= mult_res; state <= S_BM_M2; end
                S_BM_M2:  begin mult_op_a <= zrom_bm_zeta; mult_op_b <= w_m1; mult_start <= 1'b1; state <= S_BM_M2W; end
                S_BM_M2W: if (mult_done) begin w_za1b1 <= mult_res; state <= S_BM_M3; end
                S_BM_M3:  begin mult_op_a <= wa; mult_op_b <= wc; mult_start <= 1'b1; state <= S_BM_M3W; end
                S_BM_M3W: if (mult_done) begin w_a0b0 <= mult_res; state <= S_BM_WB0; end
                S_BM_WB0: begin mem_a_we <= 1'b1; mem_a_wa <= {bm_i, 1'b0}; mem_a_wd <= add_y; state <= S_BM_M4; end
                S_BM_M4:  begin mult_op_a <= wa; mult_op_b <= wd; mult_start <= 1'b1; state <= S_BM_M4W; end
                S_BM_M4W: if (mult_done) begin w_a0b1 <= mult_res; state <= S_BM_M5; end
                S_BM_M5:  begin mult_op_a <= wb; mult_op_b <= wc; mult_start <= 1'b1; state <= S_BM_M5W; end
                S_BM_M5W: if (mult_done) begin w_a1b0 <= mult_res; state <= S_BM_WB1; end
                S_BM_WB1: begin mem_a_we <= 1'b1; mem_a_wa <= {bm_i, 1'b1}; mem_a_wd <= add_y; state <= S_BM_ADV; end
                S_BM_ADV: begin
                    if (bm_i == 7'd127) state <= S_INTT_INIT;
                    else begin bm_i <= bm_i + 7'd1; state <= S_BM_LOAD; end
                end

                // ---------------- inverse NTT ----------------
                S_INTT_INIT: begin
                    layer <= 3'd0; len_reg <= 9'd2; start_reg <= 9'd0; j_reg <= 9'd0;
                    k_idx <= 7'd126;
                    state <= S_INTT_LOAD;
                end
                S_INTT_LOAD: begin wa <= a_rd0; wb <= a_rd1; state <= S_INTT_SUM; end
                S_INTT_SUM:  begin w_sum <= add_y; w_diff <= sub_y; state <= S_INTT_MUL; end
                S_INTT_MUL:  begin mult_op_a <= zrom_ntt_zeta; mult_op_b <= w_diff; mult_start <= 1'b1; state <= S_INTT_MULW; end
                S_INTT_MULW: if (mult_done) begin w_t <= mult_res; state <= S_INTT_WB0; end
                S_INTT_WB0:  begin mem_a_we <= 1'b1; mem_a_wa <= j_reg; mem_a_wd <= w_sum; state <= S_INTT_WB1; end
                S_INTT_WB1:  begin mem_a_we <= 1'b1; mem_a_wa <= j_reg + len_reg; mem_a_wd <= w_t; state <= S_INTT_ADV; end
                S_INTT_ADV: begin
                    if (j_reg + 9'd1 != start_reg + len_reg) begin
                        j_reg <= j_reg + 9'd1;
                        state <= S_INTT_LOAD;
                    end else if (start_reg + (len_reg << 1) >= 9'd256) begin
                        if (layer == 3'd6) begin
                            scale_idx <= 9'd0;
                            state <= S_SCALE_INIT;
                        end else begin
                            layer <= layer + 3'd1; len_reg <= len_reg << 1;
                            start_reg <= 9'd0; j_reg <= 9'd0; k_idx <= k_idx - 7'd1;
                            state <= S_INTT_LOAD;
                        end
                    end else begin
                        start_reg <= start_reg + (len_reg << 1);
                        j_reg     <= start_reg + (len_reg << 1);
                        k_idx     <= k_idx - 7'd1;
                        state <= S_INTT_LOAD;
                    end
                end

                // ---------------- final N_INV scaling ----------------
                S_SCALE_INIT: begin scale_idx <= 9'd0; state <= S_SCALE_LOAD; end
                S_SCALE_LOAD: begin wa <= a_rd0; state <= S_SCALE_MUL; end
                S_SCALE_MUL:  begin mult_op_a <= wa; mult_op_b <= `N_INV; mult_start <= 1'b1; state <= S_SCALE_MULW; end
                S_SCALE_MULW: if (mult_done) begin w_t <= mult_res; state <= S_SCALE_WB; end
                S_SCALE_WB:   begin mem_a_we <= 1'b1; mem_a_wa <= scale_idx; mem_a_wd <= w_t; state <= S_SCALE_ADV; end
                S_SCALE_ADV: begin
                    if (scale_idx == 9'd255) state <= S_DONE;
                    else begin scale_idx <= scale_idx + 9'd1; state <= S_SCALE_LOAD; end
                end

                S_DONE: done <= 1'b1;
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
