#!/usr/bin/env python3
"""Software reference model checks and RTL-vs-reference comparison.

Part A  (software only, always runs)
  A1  parameter derivation: zeta = 17 is a primitive 256th root of unity mod q,
      N_INV = 128^-1 mod q, Barrett constants K = 24, M = floor(2^K / q) = 5039
  A2  known-answer identities derived by hand (identity, zero, two negacyclic wraps)
  A3  for every vector in data/test_vectors/multi_{f,g,h}.mem
        NTT-based model  ==  independent schoolbook product  ==  stored multi_h.mem
      The schoolbook product below is a separate implementation (numpy convolution
      folded modulo x^256 + 1); it shares no code with the NTT model.

Part B  (needs RTL simulation output, written by scripts/verification/run_rtl_sim.sh)
  For each design the RTL output words results/sim/<design>/rtl_out.mem are compared
  with the independent schoolbook product recomputed here from f and g -- the
  comparison does not depend on multi_h.mem or on the testbench's own check.

Writes results/json/functional_verification.json and results/csv/functional_verification.csv.
Exit status 1 on any mismatch; designs without simulation output are reported SKIPPED.
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402
import kyber_ref as kr  # noqa: E402

Q, N = kr.Q, kr.N
DESIGNS = ["shared_pe", "per_phase_baseline", "pipelined_barrett"]


def read_mem(path):
    with open(path) as fh:
        return [int(x, 16) for x in fh.read().split()]


def schoolbook_numpy(f, g):
    """Independent negacyclic product: full linear convolution, then fold x^256 = -1."""
    full = np.convolve(np.asarray(f, dtype=np.int64), np.asarray(g, dtype=np.int64))
    out = full[:N].copy()
    out[: N - 1] -= full[N:]
    return [int(v) % Q for v in out]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim-dir", default=repo.SIM_DIR)
    args = ap.parse_args()
    ok_all = True
    result = {"modulus_q": Q, "ring": "Z_q[x]/(x^256+1)"}

    # ---- A1 parameters ----
    assert pow(kr.ZETA, 256, Q) == 1 and pow(kr.ZETA, 128, Q) == Q - 1
    assert all(pow(kr.ZETA, d, Q) != 1 for d in (1, 2, 4, 8, 16, 32, 64, 128))
    k_bits = 24
    m_const = (1 << k_bits) // Q
    params_ok = (kr.N_INV == 3303 and (128 * kr.N_INV) % Q == 1 and m_const == 5039)
    result["parameters"] = {"zeta": kr.ZETA, "n_inv": kr.N_INV, "barrett_K": k_bits,
                            "barrett_M": m_const, "status": "PASS" if params_ok else "FAIL"}
    print(f"[{'PASS' if params_ok else 'FAIL'}] parameters: zeta=17 primitive 256th root, "
          f"N_INV={kr.N_INV}=128^-1 mod {Q}, Barrett K={k_bits} M={m_const}")
    ok_all &= params_ok

    # ---- A2 known answers ----
    def mono(i, c=1):
        v = [0] * N
        v[i] = c
        return v
    gtest = [(7 * i + 3) % Q for i in range(N)]
    kas = {
        "identity 1*g = g": kr.ntt_polymul(mono(0), gtest) == gtest,
        "zero 0*g = 0": kr.ntt_polymul([0] * N, gtest) == [0] * N,
        "x^200*x^100 = -x^44": kr.ntt_polymul(mono(200), mono(100)) == mono(44, Q - 1),
        "x^255*x = -1": kr.ntt_polymul(mono(255), mono(1)) == mono(0, Q - 1),
    }
    result["known_answer_identities"] = {k: ("PASS" if v else "FAIL") for k, v in kas.items()}
    for k, v in kas.items():
        print(f"[{'PASS' if v else 'FAIL'}] known answer: {k}")
    ok_all &= all(kas.values())

    # ---- A3 vectors ----
    F = read_mem(os.path.join(repo.VECTORS, "multi_f.mem"))
    G = read_mem(os.path.join(repo.VECTORS, "multi_g.mem"))
    H = read_mem(os.path.join(repo.VECTORS, "multi_h.mem"))
    nvec = len(F) // N
    bad_ntt = bad_file = 0
    expected = []
    for v in range(nvec):
        f, g = F[v * N:(v + 1) * N], G[v * N:(v + 1) * N]
        ref = schoolbook_numpy(f, g)
        expected.append(ref)
        if kr.ntt_polymul(f, g) != ref:
            bad_ntt += 1
        if H[v * N:(v + 1) * N] != ref:
            bad_file += 1
    result["reference_model"] = {
        "vectors": nvec, "coefficients": nvec * N,
        "ntt_model_vs_schoolbook_mismatching_vectors": bad_ntt,
        "multi_h_vs_schoolbook_mismatching_vectors": bad_file,
        "status": "PASS" if bad_ntt == 0 and bad_file == 0 else "FAIL"}
    print(f"[{'PASS' if not (bad_ntt or bad_file) else 'FAIL'}] reference model: {nvec} vectors, "
          f"NTT model vs schoolbook mismatches={bad_ntt}, stored multi_h vs schoolbook mismatches={bad_file}")
    ok_all &= bad_ntt == 0 and bad_file == 0

    # ---- Part B RTL ----
    result["rtl"] = {}
    rows = []
    for d in DESIGNS:
        path = os.path.join(args.sim_dir, d, "rtl_out.mem")
        if not os.path.exists(path):
            result["rtl"][d] = {"status": "SKIPPED", "reason": "no RTL simulation output (xsim unavailable or not run)"}
            print(f"[SKIPPED] RTL vs schoolbook, {d}: no simulation output at {repo.rel(path)}")
            continue
        words = read_mem(path)
        n_run = len(words) // N
        mism = 0
        mism_vec = 0
        for v in range(n_run):
            bad = sum(1 for a, b in zip(words[v * N:(v + 1) * N], expected[v]) if a != b)
            mism += bad
            mism_vec += bad > 0
        status = "PASS" if (mism == 0 and n_run == nvec) else "FAIL"
        ok_all &= status == "PASS"
        result["rtl"][d] = {"tests": n_run, "coefficients_checked": n_run * N, "mismatches": mism,
                            "mismatching_vectors": mism_vec, "status": status}
        rows.append((d, n_run, n_run * N, mism, status))
        print(f"[{status}] RTL vs independent schoolbook, {d}: tests={n_run} "
              f"coefficients_checked={n_run * N} mismatches={mism}")
    repo.write_csv(os.path.join(repo.CSV_DIR, "functional_verification.csv"),
                   ["design", "tests", "coefficients_checked", "mismatches", "status"], rows)
    primary = result["rtl"].get("shared_pe", {})
    result["primary"] = {"tests": primary.get("tests"), "coefficients_checked": primary.get("coefficients_checked"),
                         "mismatches": primary.get("mismatches"), "status": primary.get("status", "SKIPPED")}
    result["status"] = "FAIL" if not ok_all else ("PASS" if primary.get("status") == "PASS" else "PARTIAL (RTL part skipped)")
    repo.write_json(os.path.join(repo.JSON_DIR, "functional_verification.json"), result)
    print(f"functional verification status: {result['status']}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
