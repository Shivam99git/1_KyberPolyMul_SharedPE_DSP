#!/usr/bin/env python3
"""Exhaustive verification of the Barrett reduction used by the modular multiplier.

Algorithm (rtl/common/mod_reduce_barrett.v), x a 24-bit unsigned input, q = 3329:
    t  = floor(x * M / 2^K)          K = 24, M = floor(2^K / q) = 5039   (13-bit t)
    r0 = x - t*q
    r1 = r0 - q  if r0 >= q  else r0 (one conditional subtraction)
    y  = r1[11:0]
Constants are re-derived here (smallest K with 2^K > (q-1)^2, M = floor(2^K/q)) and the
reducer is evaluated for EVERY x in [0, 2^24) -- the multiplier only ever produces
0 .. (q-1)^2 = 11,075,584, a strict subset -- and compared with the exact x mod q.
It also checks that one conditional subtraction always suffices (r0 < 2q), that r0 >= 0
(no wrap-around in the 25-bit RTL subtraction), and that t fits its 13-bit register.

The same algorithm is verified on the actual RTL by tb/barrett/tb_barrett_exhaustive.v;
if results/json/sim_barrett.json exists it is merged into the report.

Writes results/json/barrett_verification.json. Exit status 1 on any mismatch.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402

Q = 3329


def main():
    max_x = (Q - 1) ** 2
    k = max_x.bit_length()
    while (1 << k) <= max_x:
        k += 1
    m = (1 << k) // Q

    # check the constants that the RTL header declares
    hdr = open(os.path.join(repo.ROOT, "rtl", "common", "kyber_params.vh")).read()
    declared = {name: int(val) for name, val in __import__("re").findall(r"`define\s+BARRETT_(K|M)\s+(?:\d+'d)?(\d+)", hdr)}
    consts_ok = declared.get("K") == k and declared.get("M") == m

    x = np.arange(1 << 24, dtype=np.int64)
    t = (x * m) >> k
    r0 = x - t * Q
    r1 = np.where(r0 >= Q, r0 - Q, r0)
    y = r1 & 0xFFF
    exact = x % Q
    mismatches = int(np.count_nonzero(y != exact))
    first_bad = int(x[y != exact][0]) if mismatches else None
    res = {
        "q": Q, "K": k, "M": m, "constants_match_rtl_header": consts_ok,
        "tested_inputs": int(x.size), "min_input": int(x.min()), "max_input": int(x.max()),
        "mismatches": mismatches, "first_mismatch": first_bad,
        "max_pre_correction_remainder": int(r0.max()), "min_pre_correction_remainder": int(r0.min()),
        "single_correction_sufficient": bool(r0.max() < 2 * Q and r0.min() >= 0),
        "t_fits_13_bits": bool(t.max() < (1 << 13)),
        "r1_fits_12_bits": bool(r1.max() < (1 << 12)),
        "multiplier_input_bound": max_x,
        "mismatches_in_multiplier_range": int(np.count_nonzero((y != exact)[: max_x + 1])),
    }
    res["status"] = "PASS" if (mismatches == 0 and consts_ok and res["single_correction_sufficient"]
                               and res["t_fits_13_bits"]) else "FAIL"

    simpath = os.path.join(repo.JSON_DIR, "sim_barrett.json")
    if os.path.exists(simpath):
        sim = repo.read_json(simpath)
        res["rtl_simulation"] = {"primary": sim.get("primary"), "pipelined": sim.get("pipelined"),
                                 "status": "PASS" if sim.get("pass") else "FAIL"}
    else:
        res["rtl_simulation"] = {"status": "SKIPPED", "reason": "RTL simulation not run (xsim unavailable or not run)"}
    repo.write_json(os.path.join(repo.JSON_DIR, "barrett_verification.json"), res)

    print(f"[{res['status']}] Barrett software model: q={Q} K={k} M={m}, tested inputs={res['tested_inputs']:,}, "
          f"min={res['min_input']}, max={res['max_input']}, mismatches={mismatches}, "
          f"max pre-correction remainder={res['max_pre_correction_remainder']} (< 2q = {2 * Q})")
    print(f"[{res['rtl_simulation']['status']}] Barrett RTL simulation (primary + pipelined reducer)")
    sys.exit(0 if res["status"] == "PASS" and res["rtl_simulation"]["status"] != "FAIL" else 1)


if __name__ == "__main__":
    main()
