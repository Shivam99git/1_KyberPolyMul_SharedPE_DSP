`timescale 1ns/1ps
`include "kyber_params.vh"

// ============================================================================
// ntt_core_shared_shuffled : shuffled-issue-order variant of ntt_core_shared.v
//
//   h = INTT( NTT(f) o NTT(g) )  over Z_3329[x]/(x^256+1)
//
// WHAT IS UNCHANGED (the architecture):
//   * ONE shared mult_unit (12x12 product + Barrett reduction), ONE shared
//     mod_add, ONE shared mod_sub -- instantiated identically to
//     ntt_core_shared.v, with the identical operand multiplexers.
//   * mem_a / mem_b, 256x12 each, 2 async read ports + 1 write port, same
//     distributed-RAM inference; same zeta_rom; same top-level port list
//     (plus one optional seed input, see below).
//   * The same 38-state FSM with the same per-butterfly micro-sequence
//     (LOAD -> MUL -> MULW -> WB0 -> WB1 -> ADV), so the cycle count is
//     UNCHANGED at 27,269 and the multiplier is issued exactly 3584 times.
//
// WHAT IS CHANGED (control-FSM address generation only):
//   The plain incrementers  j_reg<=j_reg+1 / bm_i<=bm_i+1 / scale_idx<=+1
//   are replaced by an AFFINE PERMUTATION of each phase's independent-work
//   list, so the order in which independent operations are issued is
//   randomised per run:
//
//       p_{i+1} = (p_i + stride) mod M,     stride forced ODD
//
//   which is a bijection on [0,M) for M a power of two (gcd(odd,2^k)=1), so
//   every work item is still visited exactly once. start and stride are drawn
//   from a free-running 32-bit LFSR at each phase/layer entry.
//
//   Independence justification (why any order is legal):
//     - NTT/INTT: every layer holds exactly n/2 = 128 butterflies; butterfly
//       p addresses only the disjoint pair (j, j+len), and its twiddle index
//       is a function of WHICH butterfly it is, not of WHEN it issues. So the
//       128-item list of one layer may be traversed in any order. Layer order
//       itself is NOT changed (layers are data-dependent on each other).
//     - PWM: the 128 coefficient pairs are mutually independent.
//     - Scaling: the 256 coefficients are mutually independent.
//
//   Address derivation from the permuted index p (replaces j_reg/start_reg
//   incrementing).  lg = log2(len); NTT: lg = 7-layer, INTT: lg = 1+layer:
//       gi  = p >> lg                       // group index
//       off = p & (len-1)                   // offset within the group
//       j   = (gi << (lg+1)) | off          // insert a 0 bit at position lg
//       k   = k_base + gi   (NTT)   /   k_base - gi   (INTT)
//       k_base steps by +/- groups per layer, groups = 128>>lg
//   This was proved set-equivalent to the original schedule: identical 896
//   (layer,j,k) triples per transform and identical (layer,k)->{j} mapping.
//
// COST: one 32-bit LFSR, one 7-bit multiply-free adder for the affine step,
//   and the j/k decode above. No change to the arithmetic units, no change to
//   the cycle count, no change to memory structure. j_reg/k_idx/start_reg are
//   still registered (decode sits in the ADV next-state logic) so the memory
//   address path keeps the same register boundary as the original and the
//   critical path through the Barrett reduction is not lengthened.
//
// SECURITY SCOPE: this is a HIDING countermeasure. It reduces first-order
//   leakage detectability but does not remove first-order dependence; its
//   protection degrades as the attacker's trace count grows. See the
//   pre-silicon TVLA numbers in the paper for the measured reduction.
//
// SEED: rnd_seed is the LFSR seed. It must be loaded from a nondeterministic
//   source (TRNG / ring oscillator) per power-up; a constant seed makes the
//   permutation sequence predictable and voids the countermeasure. Default
//   given only so the module elaborates standalone.
// ============================================================================
module ntt_core_shared_shuffled #(
    parameter [31:0] SEED_DEFAULT = 32'hACE1_2345
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    output reg         done,

    input  wire        load_a_we,
    input  wire        load_b_we,
    input  wire [7:0]  load_addr,
    input  wire [11:0] load_data,

    input  wire [7:0]  read_addr,
    output wire [11:0] read_data,

    // NEW (optional): LFSR seed, strobe seed_we to load. Tie seed_we=0 to use
    // SEED_DEFAULT. Must come from a TRNG in a real deployment.
    input  wire        seed_we,
    input  wire [31:0] rnd_seed
);
    reg [11:0] mem_a [0:255];
    reg [11:0] mem_b [0:255];

    // ---------------- state encoding (identical to ntt_core_shared.v) -------
    localparam S_IDLE       = 6'd0,
               S_NTT_INIT   = 6'd1,
               S_NTT_LOAD   = 6'd2,
               S_NTT_MUL    = 6'd3,
               S_NTT_MULW   = 6'd4,
               S_NTT_WB0    = 6'd5,
               S_NTT_WB1    = 6'd6,
               S_NTT_ADV    = 6'd7,
               S_BM_INIT    = 6'd8,
               S_BM_LOAD    = 6'd9,
               S_BM_M1      = 6'd10,
               S_BM_M1W     = 6'd11,
               S_BM_M2      = 6'd12,
               S_BM_M2W     = 6'd13,
               S_BM_M3      = 6'd14,
               S_BM_M3W     = 6'd15,
               S_BM_WB0     = 6'd16,
               S_BM_M4      = 6'd17,
               S_BM_M4W     = 6'd18,
               S_BM_M5      = 6'd19,
               S_BM_M5W     = 6'd20,
               S_BM_WB1     = 6'd21,
               S_BM_ADV     = 6'd22,
               S_INTT_INIT  = 6'd23,
               S_INTT_LOAD  = 6'd24,
               S_INTT_SUM   = 6'd25,
               S_INTT_MUL   = 6'd26,
               S_INTT_MULW  = 6'd27,
               S_INTT_WB0   = 6'd28,
               S_INTT_WB1   = 6'd29,
               S_INTT_ADV   = 6'd30,
               S_SCALE_INIT = 6'd31,
               S_SCALE_LOAD = 6'd32,
               S_SCALE_MUL  = 6'd33,
               S_SCALE_MULW = 6'd34,
               S_SCALE_WB   = 6'd35,
               S_SCALE_ADV  = 6'd36,
               S_DONE       = 6'd37;

    reg [5:0] state;

    // ---------------- iteration / control registers ----------------
    reg       target_sel;
    reg [2:0] layer;
    reg [8:0] len_reg;
    reg [8:0] start_reg;     // kept: group start, so the register set matches
    reg [8:0] j_reg;
    reg [6:0] k_idx;
    reg [6:0] bm_i;
    reg [8:0] scale_idx;

    // ---------------- NEW: permutation state ----------------
    reg [31:0] lfsr;
    reg [7:0]  p_idx;        // permuted index (7 bits used for NTT/PWM, 8 for scale)
    reg [7:0]  perm_stride;  // odd
    reg [8:0]  item_cnt;     // 0..127 (NTT/INTT/PWM) or 0..255 (scale)
    reg [6:0]  k_base;

    // free-running LFSR, x^32 + x^30 + x^26 + x^25 + 1
    wire lfsr_fb = lfsr[31] ^ lfsr[29] ^ lfsr[25] ^ lfsr[24];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)        lfsr <= SEED_DEFAULT;
        else if (seed_we)  lfsr <= (rnd_seed == 32'd0) ? 32'd1 : rnd_seed;
        else               lfsr <= {lfsr[30:0], lfsr_fb};
    end

    // draws for a 128-item list and a 256-item list
    wire [6:0] draw7_start  = lfsr[6:0];
    wire [6:0] draw7_stride = lfsr[13:7] | 7'd1;
    wire [7:0] draw8_start  = lfsr[7:0];
    wire [7:0] draw8_stride = lfsr[15:8] | 8'd1;

    // ---------------- address decode from a permuted index ----------------
    // lg(len): NTT counts layers down from 128, INTT up from 2
    // decode for an ARBITRARY p and an ARBITRARY layer/direction, used both on
    // layer entry and on advance (so it is pure combinational next-state logic)
    function [8:0] f_j;
        input [7:0] p; input [2:0] lg;
        reg [6:0] gi; reg [6:0] off; reg [3:0] sh;
        begin
            gi  = p >> lg;
            off = p & ((7'd1 << lg) - 7'd1);
            sh  = {1'b0, lg} + 4'd1;              // 4 bits: lg=7 -> sh=8
            f_j = ({2'd0, gi} << sh) | {2'd0, off};
        end
    endfunction
    function [8:0] f_grpstart;
        input [7:0] p; input [2:0] lg;
        reg [6:0] gi; reg [3:0] sh;
        begin
            gi = p >> lg;
            sh = {1'b0, lg} + 4'd1;
            f_grpstart = ({2'd0, gi} << sh);
        end
    endfunction
    function [6:0] f_k;
        input [7:0] p; input [2:0] lg; input [6:0] kb; input is_intt;
        reg [6:0] gi;
        begin
            gi  = p >> lg;
            f_k = is_intt ? (kb - gi) : (kb + gi);
        end
    endfunction

    // lg for the CURRENT layer, per phase
    wire [2:0] lg_ntt  = 3'd7 - layer;
    wire [2:0] lg_intt = 3'd1 + layer;
    // groups in the current layer = 128>>lg
    wire [7:0] grp_ntt  = 8'd128 >> lg_ntt;
    wire [7:0] grp_intt = 8'd128 >> lg_intt;

    // ---------------- working registers (UNCHANGED) ----------------
    reg [11:0] wa, wb, wc, wd;
    reg [11:0] w_t, w_sum, w_diff;
    reg [11:0] w_m1, w_za1b1, w_a0b0, w_a0b1, w_a1b0;

    // ---------------- shared multiplier (UNCHANGED) ----------------
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

    // ---------------- shared modular add / sub (UNCHANGED) ----------------
    reg  [11:0] add_a, add_b, sub_a, sub_b;
    wire [11:0] add_y, sub_y;

    mod_add u_add (.a(add_a), .b(add_b), .y(add_y));
    mod_sub u_sub (.a(sub_a), .b(sub_b), .y(sub_y));

    always @(*) begin
        add_a = wa; add_b = w_t;
        case (state)
            S_NTT_WB0 : begin add_a = wa;     add_b = w_t;      end
            S_INTT_SUM: begin add_a = wa;     add_b = wb;       end
            S_BM_WB0  : begin add_a = w_a0b0; add_b = w_za1b1;  end
            S_BM_WB1  : begin add_a = w_a0b1; add_b = w_a1b0;   end
            default   : begin add_a = wa;     add_b = w_t;      end
        endcase
    end

    always @(*) begin
        sub_a = wa; sub_b = w_t;
        case (state)
            S_NTT_WB1 : begin sub_a = wa; sub_b = w_t; end
            S_INTT_SUM: begin sub_a = wb; sub_b = wa; end
            default   : begin sub_a = wa; sub_b = w_t; end
        endcase
    end

    // ---------------- memory read ports (UNCHANGED) ----------------
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

    // ---------------- memory write ports (UNCHANGED) ----------------
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
    // next permuted index (affine step), sized per phase
    wire [7:0] p_next7 = (p_idx + {1'b0, perm_stride[6:0]}) & 8'h7F;
    wire [7:0] p_next8 = (p_idx + perm_stride);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; done <= 1'b0; target_sel <= 1'b0;
            layer <= 3'd0; len_reg <= 9'd0; start_reg <= 9'd0; j_reg <= 9'd0;
            k_idx <= 7'd0; bm_i <= 7'd0; scale_idx <= 9'd0;
            mult_op_a <= 12'd0; mult_op_b <= 12'd0;
            wa <= 12'd0; wb <= 12'd0; wc <= 12'd0; wd <= 12'd0;
            w_t <= 12'd0; w_sum <= 12'd0; w_diff <= 12'd0;
            w_m1 <= 12'd0; w_za1b1 <= 12'd0; w_a0b0 <= 12'd0; w_a0b1 <= 12'd0; w_a1b0 <= 12'd0;
            p_idx <= 8'd0; perm_stride <= 8'd1; item_cnt <= 9'd0; k_base <= 7'd0;
        end else begin
            mult_start <= 1'b0;
            mem_a_we <= 1'b0; mem_b_we <= 1'b0;

            case (state)
                S_IDLE: begin
                    done <= 1'b0;
                    if (start) begin target_sel <= 1'b0; state <= S_NTT_INIT; end
                end

                // ---------------- forward NTT ----------------
                S_NTT_INIT: begin
                    layer <= 3'd0; len_reg <= 9'd128; k_base <= 7'd0;
                    p_idx       <= {1'b0, draw7_start};
                    perm_stride <= {1'b0, draw7_stride};
                    item_cnt    <= 9'd0;
                    j_reg     <= f_j({1'b0, draw7_start}, 3'd7);
                    start_reg <= f_grpstart({1'b0, draw7_start}, 3'd7);
                    k_idx     <= f_k({1'b0, draw7_start}, 3'd7, 7'd0, 1'b0);
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
                    if (item_cnt != 9'd127) begin
                        // next butterfly of the SAME layer, permuted order
                        p_idx    <= p_next7;
                        item_cnt <= item_cnt + 9'd1;
                        j_reg     <= f_j(p_next7, lg_ntt);
                        start_reg <= f_grpstart(p_next7, lg_ntt);
                        k_idx     <= f_k(p_next7, lg_ntt, k_base, 1'b0);
                        state <= S_NTT_LOAD;
                    end else if (layer == 3'd6) begin
                        if (!target_sel) begin
                            // second forward transform, fresh permutation
                            target_sel <= 1'b1;
                            layer <= 3'd0; len_reg <= 9'd128; k_base <= 7'd0;
                            p_idx       <= {1'b0, draw7_start};
                            perm_stride <= {1'b0, draw7_stride};
                            item_cnt    <= 9'd0;
                            j_reg     <= f_j({1'b0, draw7_start}, 3'd7);
                            start_reg <= f_grpstart({1'b0, draw7_start}, 3'd7);
                            k_idx     <= f_k({1'b0, draw7_start}, 3'd7, 7'd0, 1'b0);
                            state <= S_NTT_LOAD;
                        end else begin
                            p_idx       <= {1'b0, draw7_start};
                            perm_stride <= {1'b0, draw7_stride};
                            item_cnt    <= 9'd0;
                            bm_i        <= draw7_start;
                            state <= S_BM_INIT;
                        end
                    end else begin
                        // next layer, fresh permutation; k_base advances by groups
                        k_base  <= k_base + grp_ntt[6:0];
                        layer   <= layer + 3'd1;
                        len_reg <= len_reg >> 1;
                        p_idx       <= {1'b0, draw7_start};
                        perm_stride <= {1'b0, draw7_stride};
                        item_cnt    <= 9'd0;
                        j_reg     <= f_j({1'b0, draw7_start}, lg_ntt - 3'd1);
                        start_reg <= f_grpstart({1'b0, draw7_start}, lg_ntt - 3'd1);
                        k_idx     <= f_k({1'b0, draw7_start}, lg_ntt - 3'd1,
                                         k_base + grp_ntt[6:0], 1'b0);
                        state <= S_NTT_LOAD;
                    end
                end

                // ---------------- base multiplication ----------------
                S_BM_INIT: begin
                    p_idx       <= {1'b0, draw7_start};
                    perm_stride <= {1'b0, draw7_stride};
                    item_cnt    <= 9'd0;
                    bm_i        <= draw7_start;
                    state <= S_BM_LOAD;
                end
                S_BM_LOAD: begin
                    wa <= a_rd0; wb <= a_rd1; wc <= b_rd0; wd <= b_rd1;
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
                    if (item_cnt == 9'd127) state <= S_INTT_INIT;
                    else begin
                        p_idx    <= p_next7;
                        item_cnt <= item_cnt + 9'd1;
                        bm_i     <= p_next7[6:0];
                        state <= S_BM_LOAD;
                    end
                end

                // ---------------- inverse NTT ----------------
                S_INTT_INIT: begin
                    layer <= 3'd0; len_reg <= 9'd2; k_base <= 7'd126;
                    p_idx       <= {1'b0, draw7_start};
                    perm_stride <= {1'b0, draw7_stride};
                    item_cnt    <= 9'd0;
                    j_reg     <= f_j({1'b0, draw7_start}, 3'd1);
                    start_reg <= f_grpstart({1'b0, draw7_start}, 3'd1);
                    k_idx     <= f_k({1'b0, draw7_start}, 3'd1, 7'd126, 1'b1);
                    state <= S_INTT_LOAD;
                end
                S_INTT_LOAD: begin wa <= a_rd0; wb <= a_rd1; state <= S_INTT_SUM; end
                S_INTT_SUM:  begin w_sum <= add_y; w_diff <= sub_y; state <= S_INTT_MUL; end
                S_INTT_MUL:  begin mult_op_a <= zrom_ntt_zeta; mult_op_b <= w_diff; mult_start <= 1'b1; state <= S_INTT_MULW; end
                S_INTT_MULW: if (mult_done) begin w_t <= mult_res; state <= S_INTT_WB0; end
                S_INTT_WB0:  begin mem_a_we <= 1'b1; mem_a_wa <= j_reg; mem_a_wd <= w_sum; state <= S_INTT_WB1; end
                S_INTT_WB1:  begin mem_a_we <= 1'b1; mem_a_wa <= j_reg + len_reg; mem_a_wd <= w_t; state <= S_INTT_ADV; end
                S_INTT_ADV: begin
                    if (item_cnt != 9'd127) begin
                        p_idx    <= p_next7;
                        item_cnt <= item_cnt + 9'd1;
                        j_reg     <= f_j(p_next7, lg_intt);
                        start_reg <= f_grpstart(p_next7, lg_intt);
                        k_idx     <= f_k(p_next7, lg_intt, k_base, 1'b1);
                        state <= S_INTT_LOAD;
                    end else if (layer == 3'd6) begin
                        p_idx       <= draw8_start;
                        perm_stride <= draw8_stride;
                        item_cnt    <= 9'd0;
                        scale_idx   <= {1'b0, draw8_start};
                        state <= S_SCALE_INIT;
                    end else begin
                        k_base  <= k_base - grp_intt[6:0];
                        layer   <= layer + 3'd1;
                        len_reg <= len_reg << 1;
                        p_idx       <= {1'b0, draw7_start};
                        perm_stride <= {1'b0, draw7_stride};
                        item_cnt    <= 9'd0;
                        j_reg     <= f_j({1'b0, draw7_start}, lg_intt + 3'd1);
                        start_reg <= f_grpstart({1'b0, draw7_start}, lg_intt + 3'd1);
                        k_idx     <= f_k({1'b0, draw7_start}, lg_intt + 3'd1,
                                         k_base - grp_intt[6:0], 1'b1);
                        state <= S_INTT_LOAD;
                    end
                end

                // ---------------- final N_INV scaling ----------------
                S_SCALE_INIT: begin
                    p_idx       <= draw8_start;
                    perm_stride <= draw8_stride;
                    item_cnt    <= 9'd0;
                    scale_idx   <= {1'b0, draw8_start};
                    state <= S_SCALE_LOAD;
                end
                S_SCALE_LOAD: begin wa <= a_rd0; state <= S_SCALE_MUL; end
                S_SCALE_MUL:  begin mult_op_a <= wa; mult_op_b <= `N_INV; mult_start <= 1'b1; state <= S_SCALE_MULW; end
                S_SCALE_MULW: if (mult_done) begin w_t <= mult_res; state <= S_SCALE_WB; end
                S_SCALE_WB:   begin mem_a_we <= 1'b1; mem_a_wa <= scale_idx; mem_a_wd <= w_t; state <= S_SCALE_ADV; end
                S_SCALE_ADV: begin
                    if (item_cnt == 9'd255) state <= S_DONE;
                    else begin
                        p_idx     <= p_next8;
                        item_cnt  <= item_cnt + 9'd1;
                        scale_idx <= {1'b0, p_next8};
                        state <= S_SCALE_LOAD;
                    end
                end

                S_DONE: done <= 1'b1;
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
