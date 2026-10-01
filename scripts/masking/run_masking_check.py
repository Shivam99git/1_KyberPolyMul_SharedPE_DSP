#!/usr/bin/env python3
"""Additive-masking protocol: correctness checks (model and RTL) and latency overhead.

Protocol (usage of the UNMODIFIED primary core, no RTL change):
    f = f1 + f2 (mod q), f1 uniform;  h = core(f1, g) + core(f2, g)  (mod q, addition outside the core)

Checks
  M1  model: 50 operand pairs (5 directed corner cases + 45 random) x 5 independent masks =
      250 masked products, each compared with an independent schoolbook product
  M2  RTL: results/json/sim_masking.json (tb_masking.v: core(f1,g) + core(f2,g) == core(f,g) ==
      golden product, 3 invocations per vector) if the RTL simulation was run
  M3  latency: two invocations = 2 x the single-invocation latency
The leakage experiment (TVLA of the masked protocol) is scripts/tvla/run_tvla.py --experiments masked.
Writes results/json/masking_verification.json; exit 1 on any failure.
"""
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
sys.path.insert(0, os.path.join(HERE, "..", "tvla"))
import repo  # noqa: E402
import masking  # noqa: E402

Q = 3329
SEED = 2024


def schoolbook(f, g):
    full = np.convolve(np.asarray(f, dtype=np.int64), np.asarray(g, dtype=np.int64))
    out = full[:256].copy()
    out[:255] -= full[256:]
    return [int(v) % Q for v in out]


def main():
    rnd = random.Random(SEED)
    z = [0] * 256
    one = [1] + [0] * 255
    qm1 = [Q - 1] * 256
    x255 = [0] * 255 + [1]
    x1 = [0, 1] + [0] * 254
    x200 = [0] * 200 + [1] + [0] * 55
    x100 = [0] * 100 + [1] + [0] * 155
    rnd_poly = lambda: [rnd.randrange(Q) for _ in range(256)]  # noqa: E731
    pairs = [(z, rnd_poly()), (one, rnd_poly()), (qm1, qm1), (x255, x1), (x200, x100)] + \
            [(rnd_poly(), rnd_poly()) for _ in range(45)]
    n_masks = 5
    fails = runs = 0
    for f, g in pairs:
        exp = schoolbook(f, g)
        for t in range(n_masks):
            out, cyc, _ = masking.masked_run(f, g, random.Random(1000 + t))
            runs += 1
            fails += out != exp
    out, cyc2, _ = masking.masked_run(pairs[5][0], pairs[5][1], random.Random(1))
    import core_model as cm
    _, cyc1, _ = cm.run(pairs[5][0], pairs[5][1], True)
    res = {"model": {"operand_pairs": len(pairs), "masks_per_pair": n_masks, "masked_products": runs, "failures": int(fails),
                     "seed": SEED, "mask_seeds": [1000 + t for t in range(n_masks)],
                     "status": "PASS" if fails == 0 else "FAIL"},
           "latency": {"single_invocation_cycles_model": cyc1 + 1, "masked_cycles_model": cyc2 + 2,
                       "ratio": (cyc2 + 2) / (cyc1 + 1)}}
    sim = os.path.join(repo.JSON_DIR, "sim_masking.json")
    if os.path.exists(sim):
        s = repo.read_json(sim)
        res["rtl"] = {"vectors": s.get("vectors"), "invocations": s.get("invocations"), "coefficients": s.get("coefficients"),
                      "mismatches_vs_unmasked_core": s.get("mismatches_vs_unmasked_core"),
                      "mismatches_vs_golden": s.get("mismatches_vs_golden"),
                      "masked_latency_cycles": s.get("masked_latency_min"),
                      "latency_ratio": (s["masked_latency_min"] / 27269.0) if s.get("masked_latency_min") else None,
                      "status": "PASS" if s.get("pass") else "FAIL"}
    else:
        res["rtl"] = {"status": "SKIPPED", "reason": "RTL simulation not run (xsim unavailable or not run)"}
    tv = os.path.join(repo.JSON_DIR, "tvla_summary.json")
    if os.path.exists(tv):
        m = repo.read_json(tv)["experiments"].get("masked")
        if m:
            res["tvla"] = {k: m[k] for k in ("n_per_group", "samples", "cycles_evaluated", "max_abs_t", "n_above_threshold",
                                              "expected_false_positives", "null_max_abs_t", "seeds")}
    res["status"] = "FAIL" if (fails or res["rtl"]["status"] == "FAIL") else "PASS"
    repo.write_json(os.path.join(repo.JSON_DIR, "masking_verification.json"), res)
    print(f"[{res['model']['status']}] masking model: {runs} masked products ({len(pairs)} pairs x {n_masks} masks), failures={fails}")
    print(f"[{res['rtl']['status']}] masking RTL: core(f1,g)+core(f2,g) == core(f,g) == golden"
          + (f", vectors={res['rtl']['vectors']}, mismatches={res['rtl']['mismatches_vs_golden']}" if res['rtl']['status'] != 'SKIPPED' else ""))
    print(f"[INFO] masked latency: {cyc2 + 2:,} cycles in the model = {res['latency']['ratio']:.2f}x the unmasked {cyc1 + 1:,}")
    sys.exit(1 if res["status"] == "FAIL" else 0)


if __name__ == "__main__":
    main()
