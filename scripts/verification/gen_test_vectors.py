#!/usr/bin/env python3
"""Deterministically regenerate every vector / ROM file in data/test_vectors/.

Default mode is --check: regenerate in memory and compare byte-for-byte with the
checked-in files (non-zero exit on any difference). Use --write to (re)write them.

Files
  zetas_ntt.mem, zetas_basemul.mem      twiddle ROM images (derived, not copied)
  poly_f.mem, poly_g.mem, expected_h.mem single directed example (seed 42)
  multi_f.mem, multi_g.mem, multi_h.mem  256 vectors: 16 directed corner cases +
                                          240 random pairs (seed 777; corner r seed 999);
                                          expected h = NTT product, cross-checked against
                                          schoolbook before being written
  saif_manuscript/, saif_random/         4-vector stimulus sets for the SAIF power runs
  masking_f1.mem                         256 random mask polynomials f1 (seed 0x4D41534B)

Every .mem file holds one 12-bit word per line, three lowercase hex digits.
"""
import argparse
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402
from kyber_ref import (Q, N, ZETA_NTT, ZETA_BASEMUL, ntt, intt, basemul,  # noqa: E402
                       ntt_polymul, schoolbook_mul)

N_RANDOM = 240
SEED_RANDOM = 777
SEED_CORNER_R = 999
SEED_DIRECTED = 42
SEED_MASK = 0x4D41534B


def zero():
    return [0] * N


def const(c):
    v = zero()
    v[0] = c
    return v


def monomial(i, c=1):
    v = zero()
    v[i] = c % Q
    return v


def allval(c):
    return [c % Q] * N


def ramp():
    return [i % Q for i in range(N)]


def known_answer_checks():
    """Hand-derived answers that validate the golden model itself."""
    g = [(7 * i + 3) % Q for i in range(N)]
    assert ntt_polymul(const(1), g) == g, "identity failed"
    assert ntt_polymul(zero(), g) == zero(), "zero failed"
    exp = zero()
    exp[44] = Q - 1                                   # x^200 * x^100 = x^300 = -x^44
    assert ntt_polymul(monomial(200), monomial(100)) == exp, "negacyclic wrap failed"
    exp = zero()
    exp[0] = Q - 1                                    # x^255 * x = x^256 = -1
    assert ntt_polymul(monomial(255), monomial(1)) == exp, "x^256 = -1 failed"
    return ["identity 1*g=g", "zero 0*g=0", "wrap x^200*x^100=-x^44", "x^255*x=-1"]


def corner_pairs():
    rng = random.Random(SEED_CORNER_R)
    r = [rng.randrange(Q) for _ in range(N)]
    return [
        (zero(), r), (r, zero()), (const(1), r), (r, const(1)), (const(Q - 1), r),
        (allval(Q - 1), allval(Q - 1)), (allval(Q - 1), allval(1)), (allval(1), allval(1)),
        (monomial(1), r), (monomial(255), monomial(1)), (monomial(200), monomial(100)),
        (monomial(0, Q - 1), monomial(0, Q - 1)), (ramp(), ramp()), (r, r),
        (allval(Q - 1), r), (monomial(128), monomial(128)),
    ]


def mem_text(values):
    return "".join(f"{int(v):03x}\n" for v in values)


def build():
    files = {}
    files["zetas_ntt.mem"] = mem_text(ZETA_NTT[1:128])
    files["zetas_basemul.mem"] = mem_text(ZETA_BASEMUL)

    rng = random.Random(SEED_DIRECTED)
    f = [rng.randrange(Q) for _ in range(N)]
    g = [rng.randrange(Q) for _ in range(N)]
    h = intt(basemul(ntt(f), ntt(g)))
    assert h == schoolbook_mul(f, g), "directed example failed self-check"
    files["poly_f.mem"] = mem_text(f)
    files["poly_g.mem"] = mem_text(g)
    files["expected_h.mem"] = mem_text(h)

    known_answer_checks()
    pairs = corner_pairs()
    rng = random.Random(SEED_RANDOM)
    for _ in range(N_RANDOM):
        pairs.append(([rng.randrange(Q) for _ in range(N)], [rng.randrange(Q) for _ in range(N)]))
    fa, ga, ha = [], [], []
    for a, b in pairs:
        h1 = ntt_polymul(a, b)
        assert h1 == schoolbook_mul(a, b), "golden mismatch while generating multi vectors"
        fa += a
        ga += b
        ha += h1
    files["multi_f.mem"], files["multi_g.mem"], files["multi_h.mem"] = map(mem_text, (fa, ga, ha))

    # SAIF stimulus sets (4 vectors each)
    one = const(1)
    rnd1 = [random.Random(1).randrange(Q) for _ in range(N)]
    rnd2 = [random.Random(2).randrange(Q) for _ in range(N)]
    man = [(zero(), zero()), (zero(), rnd1), (one, one), (one, rnd2)]
    rr = [([random.Random(0xC0FFEE + 2 * s).randrange(Q) for _ in range(N)],
           [random.Random(0xC0FFEE + 2 * s + 1).randrange(Q) for _ in range(N)]) for s in range(4)]
    for name, vecs in (("saif_manuscript", man), ("saif_random", rr)):
        f4, g4, h4 = [], [], []
        for a, b in vecs:
            f4 += a
            g4 += b
            h4 += schoolbook_mul(a, b)
        files[f"{name}/multi_f.mem"], files[f"{name}/multi_g.mem"], files[f"{name}/multi_h.mem"] = \
            map(mem_text, (f4, g4, h4))

    rng = random.Random(SEED_MASK)
    files["masking_f1.mem"] = mem_text([rng.randrange(Q) for _ in range(256 * N)])
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write the regenerated files (default: only check)")
    ap.add_argument("--out-dir", default=repo.VECTORS)
    args = ap.parse_args()
    files = build()
    bad = 0
    for name, text in sorted(files.items()):
        path = os.path.join(args.out_dir, name)
        if args.write:
            repo.ensure(os.path.dirname(path))
            with open(path, "w") as fh:
                fh.write(text)
            print(f"wrote {repo.rel(path)}")
        else:
            cur = open(path).read() if os.path.exists(path) else None
            ok = cur == text
            bad += 0 if ok else 1
            print(f"[{'PASS' if ok else 'FAIL'}] {repo.rel(path)} {'identical to regenerated' if ok else 'differs / missing'}")
    if not args.write:
        print(f"{len(files) - bad}/{len(files)} vector files reproduced byte-for-byte")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
