#!/usr/bin/env python3
"""
Golden reference model for Kyber's NTT-based polynomial multiplication.

n = 256, q = 3329. All constants (bit-reversal table, zeta powers, modular
inverse) are derived here programmatically rather than copied from memory,
so this script is the single source of truth for:
  - the zeta ROM contents used by the RTL (zetas_ntt.mem, zetas_basemul.mem)
  - the test vectors used by the RTL testbenches (vectors/*.mem)
  - the correctness oracle: NTT-based multiplication is checked against
    brute-force schoolbook multiplication mod (x^256+1) before anything
    is trusted or exported.
"""
import random

Q = 3329
N = 256
ZETA = 17  # candidate primitive 256th root of unity mod Q


def bitrev7(x: int) -> int:
    r = 0
    for _ in range(7):
        r = (r << 1) | (x & 1)
        x >>= 1
    return r


def check_primitive_root():
    assert pow(ZETA, 256, Q) == 1, "zeta^256 != 1 mod q"
    assert pow(ZETA, 128, Q) == Q - 1, "zeta^128 != -1 mod q"
    # order must be exactly 256 (not a proper divisor)
    for d in (1, 2, 4, 8, 16, 32, 64, 128):
        assert pow(ZETA, d, Q) != 1, f"zeta has order dividing {d}, not primitive"


check_primitive_root()

# ZETA_NTT[k] for k = 1..127, used by both forward and inverse NTT layers
ZETA_NTT = [0] * 128
for k in range(1, 128):
    ZETA_NTT[k] = pow(ZETA, bitrev7(k), Q)

# ZETA_BASEMUL[i] for i = 0..127, used by the degree-2 base multiplication
ZETA_BASEMUL = [0] * 128
for i in range(128):
    ZETA_BASEMUL[i] = pow(ZETA, 2 * bitrev7(i) + 1, Q)

N_INV = pow(128, -1, Q)  # 128^{-1} mod q, final INTT scaling constant


def ntt(f_in):
    f = list(f_in)
    k = 1
    length = 128
    while length >= 2:
        start = 0
        while start < N:
            zeta = ZETA_NTT[k]
            k += 1
            for j in range(start, start + length):
                t = (zeta * f[j + length]) % Q
                f[j + length] = (f[j] - t) % Q
                f[j] = (f[j] + t) % Q
            start += 2 * length
        length //= 2
    return f


def intt(f_in):
    f = list(f_in)
    k = 127
    length = 2
    while length <= 128:
        start = 0
        while start < N:
            zeta = ZETA_NTT[k]
            k -= 1
            for j in range(start, start + length):
                t = f[j]
                f[j] = (t + f[j + length]) % Q
                f[j + length] = (zeta * ((f[j + length] - t) % Q)) % Q
            start += 2 * length
        length *= 2
    return [(x * N_INV) % Q for x in f]


def basecase_multiply(a0, a1, b0, b1, zeta):
    c0 = (a0 * b0 + zeta * ((a1 * b1) % Q)) % Q
    c1 = (a0 * b1 + a1 * b0) % Q
    return c0, c1


def basemul(f_hat, g_hat):
    h = [0] * N
    for i in range(128):
        c0, c1 = basecase_multiply(
            f_hat[2 * i], f_hat[2 * i + 1],
            g_hat[2 * i], g_hat[2 * i + 1],
            ZETA_BASEMUL[i],
        )
        h[2 * i], h[2 * i + 1] = c0, c1
    return h


def ntt_polymul(f, g):
    """Full NTT-based polynomial multiplication: INTT(NTT(f) o NTT(g))."""
    return intt(basemul(ntt(f), ntt(g)))


def schoolbook_mul(f, g):
    """Reference O(n^2) multiplication in Z_q[x]/(x^n+1)."""
    prod = [0] * (2 * N - 1)
    for i in range(N):
        if f[i] == 0:
            continue
        for j in range(N):
            prod[i + j] = (prod[i + j] + f[i] * g[j]) % Q
    out = prod[:N]
    for i in range(N, 2 * N - 1):
        out[i - N] = (out[i - N] - prod[i]) % Q
    return out


def self_test(trials=20, seed=1):
    rng = random.Random(seed)
    for t in range(trials):
        f = [rng.randrange(Q) for _ in range(N)]
        g = [rng.randrange(Q) for _ in range(N)]
        h_ntt = ntt_polymul(f, g)
        h_ref = schoolbook_mul(f, g)
        assert h_ntt == h_ref, f"mismatch on trial {t}"
    print(f"self_test OK: {trials} random trials, NTT-based multiplication "
          f"matches schoolbook mod (x^{N}+1) over Z_{Q}")


if __name__ == "__main__":
    self_test()
    print(f"ZETA={ZETA}, N_INV={N_INV}")
    print(f"ZETA_NTT[1..5] = {ZETA_NTT[1:6]}")
    print(f"ZETA_BASEMUL[0..4] = {ZETA_BASEMUL[0:5]}")
