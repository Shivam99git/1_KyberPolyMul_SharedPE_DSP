// Constants for q = 3329. Barrett constants (K, M, correction count) are re-derived
// and exhaustively checked by scripts/verification/barrett_exhaustive.py.
`ifndef KYBER_PARAMS_VH
`define KYBER_PARAMS_VH

`define Q            12'd3329
`define Q_WIDTH      12
`define N_COEFFS     256
`define N_INV        12'd3303      // 128^-1 mod q, final INTT scaling constant

// Barrett reduction constants for reducing a 24-bit product mod Q
`define BARRETT_K    24
`define BARRETT_M    25'd5039
`define BARRETT_MAX_EXTRA_SUB 1

`endif
