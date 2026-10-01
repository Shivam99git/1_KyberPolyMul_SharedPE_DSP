#!/usr/bin/env python3
"""Shuffled-issue-order countermeasure: schedule equivalence, correctness and cost checks.

Notation: L = number of schedulable work items of one list (L = 128 for every NTT/INTT
layer and for base multiplication, L = 256 for the scaling pass). L is used for the
permutation modulus so that it is not confused with the Barrett constant M = 5039.

Construction (rtl/shared_pe/ntt_core_shared_shuffled.v):
    p_0 = start,  p_{i+1} = (p_i + stride) mod L,  stride forced odd
    start, stride drawn from a free-running 32-bit LFSR (x^32+x^30+x^26+x^25+1) at each
    phase / layer entry. gcd(odd, 2^k) = 1, so the map is a bijection: every item visited once.
    NTT / INTT address decode: lg = 7-layer (NTT) or 1+layer (INTT); gi = p >> lg;
    j = (gi << (lg+1)) | (p & (len-1)); k = k_base +/- gi.

Checks
  S1  schedule: for EVERY (start, odd stride) pair of every layer of both transforms the visited
      set {(layer, j, k)} equals the original schedule's; same for PWM and scaling index lists
  S2  per-item marginal: over all (start, stride) each work item lands in each time slot equally often
  S3  model: 50 vectors x 6 LFSR seeds x {shared, per-phase} + 50 unshuffled runs = 650 runs;
      product == schoolbook, cycle count and multiplier issues unchanged
  S4  RTL (if simulated): results/json/sim_shuffled.json
  S5  cost: flip-flops declared by the new permutation registers, counted from the RTL source
Writes results/json/shuffling_verification.json; exit 1 on any failure.
"""
import os
import random
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
sys.path.insert(0, os.path.join(HERE, "..", "tvla"))
import repo  # noqa: E402
import core_model as cm  # noqa: E402

Q = 3329
SEEDS = [0xACE12345, 0x1, 0xFFFFFFFF, 0xDEADBEEF, 0x5A5A5A5A, 0x13579BDF]


def original_triples(is_intt):
    """(layer, j, k) of the original incrementing schedule (reference model of the FSM)."""
    out = set()
    k = 126 if is_intt else 0
    for layer in range(7):
        length = (2 << layer) if is_intt else (128 >> layer)
        start = 0
        while start < 256:
            for j in range(start, start + length):
                out.add((layer, j, k))
            k += -1 if is_intt else 1
            start += 2 * length
        # k continues across layers exactly like the RTL's k_idx
    return out


def shuffled_triples(is_intt, start, stride):
    out = set()
    kb = 126 if is_intt else 0
    for layer in range(7):
        lg = (1 + layer) if is_intt else (7 - layer)
        p = np.array([(start + i * stride) & 127 for i in range(128)])
        gi = p >> lg
        j = (gi << (lg + 1)) | (p & ((1 << lg) - 1))
        k = (kb - gi) if is_intt else (kb + gi)
        out.update(zip([layer] * 128, j.tolist(), k.tolist()))
        kb += -(128 >> lg) if is_intt else (128 >> lg)
    return out


def schoolbook(f, g):
    full = np.convolve(np.asarray(f, dtype=np.int64), np.asarray(g, dtype=np.int64))
    out = full[:256].copy()
    out[:255] -= full[256:]
    return [int(v) % Q for v in out]


def main():
    res = {"notation": "L = number of schedulable work items (128 per NTT/INTT layer and PWM, 256 for scaling)"}
    ok = True

    # S1 schedule equivalence over all (start, odd stride) pairs
    pairs = 0
    bad = 0
    for is_intt in (False, True):
        ref = original_triples(is_intt)
        assert len(ref) == 896
        for start in range(128):
            for stride in range(1, 128, 2):
                pairs += 1
                bad += shuffled_triples(is_intt, start, stride) != ref
    idx_bad = 0
    idx_pairs = 0
    for size in (128, 256):
        for start in range(size):
            for stride in range(1, size, 2):
                idx_pairs += 1
                idx_bad += len({(start + i * stride) % size for i in range(size)}) != size
    res["schedule_equivalence"] = {"ntt_intt_start_stride_pairs_checked": pairs, "triples_per_transform": 896,
                                   "pairs_with_different_schedule": bad, "pwm_scale_index_pairs_checked": idx_pairs,
                                   "pairs_not_a_bijection": idx_bad, "status": "PASS" if (bad == 0 and idx_bad == 0) else "FAIL"}
    ok &= bad == 0 and idx_bad == 0

    # S2 marginal uniformity
    uni = {}
    for size in (128, 256):
        counts = np.zeros((size, size), dtype=np.int64)
        for start in range(size):
            for stride in range(1, size, 2):
                p = (start + np.arange(size) * stride) % size       # item at each slot
                counts[p, np.arange(size)] += 1
        uni[f"L={size}"] = {"min_count": int(counts.min()), "max_count": int(counts.max()),
                            "uniform": bool(counts.min() == counts.max())}
    res["marginal_uniformity"] = uni
    ok &= all(v["uniform"] for v in uni.values())

    # S3 model correctness / cost invariance
    rnd = random.Random(31337)
    z = [0] * 256
    one = [1] + [0] * 255
    qm1 = [Q - 1] * 256
    x255 = [0] * 255 + [1]
    x1 = [0, 1] + [0] * 254
    x200 = [0] * 200 + [1] + [0] * 55
    x100 = [0] * 100 + [1] + [0] * 155
    rp = lambda: [rnd.randrange(Q) for _ in range(256)]  # noqa: E731
    vecs = [(z, rp()), (one, rp()), (qm1, qm1), (x255, x1), (x200, x100), ([1] * 256, [1] * 256)] + \
           [(rp(), rp()) for _ in range(44)]
    fails = runs = 0
    cyc_set, issue_set = set(), set()
    for f, g in vecs:
        exp = schoolbook(f, g)
        c0, k0, _ = cm.run(f, g, True, shuffle=False)
        runs += 1
        fails += c0.mem_a != exp
        cyc_set.add(k0)
        issue_set.add(c0.issues)
        for sd in SEEDS:
            for shared in (True, False):
                c, k, _ = cm.run(f, g, shared, shuffle=True, seed=sd)
                runs += 1
                fails += c.mem_a != exp
                cyc_set.add(k)
                issue_set.add(c.issues)
    res["model"] = {"vectors": len(vecs), "lfsr_seeds": [f"{s:#010x}" for s in SEEDS], "runs": runs, "failures": int(fails),
                    "cycles_before_done_state": sorted(cyc_set), "multiplier_issues": sorted(issue_set),
                    "status": "PASS" if (fails == 0 and len(cyc_set) == 1 and issue_set == {3584}) else "FAIL"}
    ok &= res["model"]["status"] == "PASS"

    # S4 RTL
    sim = os.path.join(repo.JSON_DIR, "sim_shuffled.json")
    if os.path.exists(sim):
        s = repo.read_json(sim)
        res["rtl"] = {k: s.get(k) for k in ("runs", "coefficients", "mismatches", "cycles_min", "cycles_max", "distinct_seed_hashes",
                                            "runs_with_wrong_issue_count", "runs_with_seed_trace_hash_change")}
        res["rtl"]["status"] = "PASS" if s.get("pass") else "FAIL"
        ok &= bool(s.get("pass"))
    else:
        res["rtl"] = {"status": "SKIPPED", "reason": "RTL simulation not run (xsim unavailable or not run)"}

    # S5 declared flip-flops of the permutation state
    src = open(os.path.join(repo.ROOT, "rtl", "shared_pe", "ntt_core_shared_shuffled.v")).read()
    regs = {}
    for name in ("lfsr", "p_idx", "perm_stride", "item_cnt", "k_base"):
        m = re.search(r"reg\s*\[(\d+):0\]\s+" + name + r"\b", src)
        regs[name] = int(m.group(1)) + 1 if m else None
    res["added_state"] = {"declared_register_bits": regs, "total_flip_flops": sum(v for v in regs.values() if v),
                          "note": "counted from the RTL declarations; the mapped count is in the optional synthesis of the shuffled core"}

    # TVLA numbers if available
    tv = os.path.join(repo.JSON_DIR, "tvla_summary.json")
    if os.path.exists(tv):
        t = repo.read_json(tv)["experiments"]
        if "shuffle_on" in t and "shuffle_off" in t:
            res["tvla"] = {"matched_control": {k: t["shuffle_off"][k] for k in ("max_abs_t", "n_above_threshold", "cycles_evaluated")},
                           "shuffled": {k: t["shuffle_on"][k] for k in ("max_abs_t", "n_above_threshold", "cycles_evaluated",
                                                                           "expected_false_positives", "null_max_abs_t")}}
    res["status"] = "PASS" if ok else "FAIL"
    repo.write_json(os.path.join(repo.JSON_DIR, "shuffling_verification.json"), res)
    se = res["schedule_equivalence"]
    print(f"[{se['status']}] schedule equivalence: {se['ntt_intt_start_stride_pairs_checked']:,} (start, stride) pairs x 2 transforms, "
          f"{se['pairs_with_different_schedule']} differ; {se['pwm_scale_index_pairs_checked']:,} index-list pairs, {se['pairs_not_a_bijection']} not a bijection")
    print(f"[{'PASS' if all(v['uniform'] for v in uni.values()) else 'FAIL'}] per-item slot distribution uniform: {uni}")
    print(f"[{res['model']['status']}] shuffled model: {runs} runs, failures={fails}, cycles={sorted(cyc_set)}, issues={sorted(issue_set)}")
    print(f"[{res['rtl']['status']}] shuffled RTL simulation")
    print(f"[INFO] permutation state = {res['added_state']['total_flip_flops']} flip-flops declared {regs}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
