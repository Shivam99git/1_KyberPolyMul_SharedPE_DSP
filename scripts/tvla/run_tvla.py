#!/usr/bin/env python3
"""Generate the raw TVLA data (per-clock-cycle first/second moments) for every
simulated leakage experiment in the manuscript.

Leakage model  : per-clock-cycle Hamming distance between successive snapshots of
                 every register the RTL declares (scripts/tvla/core_model.py).
Methodology    : fixed-vs-random. Secret operand f is fixed in one group and random
                 in the other; the public operand g is random in both.
Null           : two independent random-vs-random groups with the same trace count.
Statistic      : Welch's t per clock cycle, threshold |t| > 4.5 (scripts/tvla/analyze_tvla.py).

Experiments (names are used by analyze_tvla.py):
  main_shared / main_baseline       400 traces/group, shared-PE and per-phase cores
  multi_shared / multi_baseline     5 independent random fixed secrets, 200 traces/group
  multiconst_shared / multiconst_baseline
                                    the same test exactly as it was originally run: each
                                    "fixed secret" is a CONSTANT polynomial (all 256
                                    coefficients equal; see multi_secret_constant() below)
  shuffle_off / shuffle_on          shared-PE core without / with the affine shuffle
  masked                            additive masking, two invocations of the core

Every group is an independent job with its own seeded RNG, accumulated strictly in
trace order, so the result is bit-identical for any number of worker processes.
The raw output is an int32 (sum, sum-of-squares) pair per group and clock cycle;
sums of integer Hamming distances are exact, so no precision is lost.

Usage:  python3 scripts/tvla/run_tvla.py [--traces 400] [--multi-traces 200]
            [--experiments main_shared,...] [--jobs N] [--out-dir DIR]
"""
import argparse
import concurrent.futures as cf
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import core_model as cm  # noqa: E402
import masking  # noqa: E402
import repo  # noqa: E402

Q = 3329
SECRET_SEED = 20260922            # seeds the fixed secret f used by main/shuffle/masked
GROUP_SEEDS = {"fix": 1001, "rand": 2002, "null_a": 3003, "null_b": 4004}
MULTI_SECRET_SEED_BASE = 7000     # fixed secret k: Random(7000+k)
MULTI_GROUP_SEED_BASE = 8000      # group seeds: 8000+2k (fixed), 8001+2k (random)
N_SECRETS = 5
ALL = ["main_shared", "main_baseline", "multi_shared", "multi_baseline",
       "multiconst_shared", "multiconst_baseline", "shuffle_off", "shuffle_on", "masked"]


def fixed_secret():
    rnd = random.Random(SECRET_SEED)
    return [rnd.randrange(Q) for _ in range(256)]


def multi_secret(k):
    """Secret k: 256 independent uniform coefficients from ONE generator seeded 7000+k."""
    rr = random.Random(MULTI_SECRET_SEED_BASE + k)
    return [rr.randrange(Q) for _ in range(256)]


def multi_secret_constant(k):
    """Secret k exactly as the original experiment script built it.

    The original expression  [random.Random(7000+k).randrange(Q) for _ in range(256)]
    constructs a NEW generator for every coefficient, so all 256 coefficients take the
    same value (1320, 481, 2290, 2699, 615 for k = 0..4): the 'secret' is a constant
    polynomial, not a random one. Kept only to reproduce the manuscript's five-secret
    numbers; the corrected experiment is multi_shared / multi_baseline.
    """
    return [random.Random(MULTI_SECRET_SEED_BASE + k).randrange(Q) for _ in range(256)]


def run_group(spec):
    """Accumulate one group of traces. Returns (exp, group, n, sum, sumsq)."""
    exp, group, kind, shared, shuffle, mode, n, seed, f_fix = spec
    r = random.Random(seed)
    s = ss = None
    for _ in range(n):
        f = list(f_fix) if mode == "fix" else [r.randrange(Q) for _ in range(256)]
        g = [r.randrange(Q) for _ in range(256)]
        if kind == "masked":
            _, _, p = masking.masked_run(f, g, r, trace=True)
        elif kind == "shuffle":
            sd = r.randrange(1, 1 << 32)     # LFSR seed; drawn even when shuffling is off
            _, _, p = cm.run(f, g, True, shuffle=shuffle, seed=sd, trace=True)
        else:
            _, _, p = cm.run(f, g, shared, trace=True)
        a = np.asarray(p, dtype=np.int64)
        if s is None:
            s = np.zeros_like(a)
            ss = np.zeros_like(a)
        s += a
        ss += a * a
    return exp, group, n, s, ss


def plan(experiments, n, n_multi):
    f_fix = fixed_secret()
    jobs = []
    groups = ("fix", "rand", "null_a", "null_b")
    for exp in experiments:
        if exp in ("main_shared", "main_baseline"):
            shared = exp == "main_shared"
            for gname in groups:
                jobs.append((exp, gname, "core", shared, False,
                             "fix" if gname == "fix" else "rand", n, GROUP_SEEDS[gname], f_fix))
        elif exp in ("shuffle_off", "shuffle_on"):
            for gname in groups:
                jobs.append((exp, gname, "shuffle", True, exp == "shuffle_on",
                             "fix" if gname == "fix" else "rand", n, GROUP_SEEDS[gname], f_fix))
        elif exp == "masked":
            for gname in groups:
                jobs.append((exp, gname, "masked", True, False,
                             "fix" if gname == "fix" else "rand", n, GROUP_SEEDS[gname], f_fix))
        elif exp in ("multi_shared", "multi_baseline", "multiconst_shared", "multiconst_baseline"):
            shared = exp.endswith("_shared")
            for k in range(N_SECRETS):
                fx = multi_secret_constant(k) if exp.startswith("multiconst") else multi_secret(k)
                jobs.append((exp, f"fix{k}", "core", shared, False, "fix", n_multi,
                             MULTI_GROUP_SEED_BASE + 2 * k, fx))
                jobs.append((exp, f"rand{k}", "core", shared, False, "rand", n_multi,
                             MULTI_GROUP_SEED_BASE + 2 * k + 1, fx))
        else:
            repo.die(f"unknown experiment '{exp}' (choose from {', '.join(ALL)})")
    return jobs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--traces", type=int, default=400, help="traces per group (default 400)")
    ap.add_argument("--multi-traces", type=int, default=200, help="traces per group, multi-secret (default 200)")
    ap.add_argument("--experiments", default=",".join(ALL), help="comma separated subset of: " + ",".join(ALL))
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                    help="worker processes (default: all cores but one)")
    ap.add_argument("--out-dir", default=repo.TVLA_GEN,
                    help="output directory for the raw moment files (default results/tvla_raw)")
    args = ap.parse_args()

    experiments = [e for e in args.experiments.split(",") if e]
    jobs = plan(experiments, args.traces, args.multi_traces)
    repo.ensure(args.out_dir)
    print(f"[tvla] {len(jobs)} groups, {args.jobs} workers, traces/group={args.traces} "
          f"(multi-secret {args.multi_traces}); seeds: secret={SECRET_SEED} groups={GROUP_SEEDS} "
          f"multi={MULTI_SECRET_SEED_BASE}/{MULTI_GROUP_SEED_BASE}", flush=True)
    t0 = time.time()
    results = {}
    with cf.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(run_group, j): j for j in jobs}
        for fut in cf.as_completed(futs):
            exp, group, n, s, ss = fut.result()
            results.setdefault(exp, {})[group] = (n, s, ss)
            print(f"[tvla]   done {exp}/{group} ({time.time() - t0:.0f}s)", flush=True)

    for exp, groups in results.items():
        payload = {"experiment": np.array(exp)}
        for gname, (n, s, ss) in groups.items():
            if int(ss.max()) >= 2 ** 31:
                repo.die("second moment exceeds int32; widen the storage type")
            payload[f"{gname}__n"] = np.array(n)
            payload[f"{gname}__s"] = s.astype(np.int32)
            payload[f"{gname}__ss"] = ss.astype(np.int32)
        payload["seeds"] = np.array([SECRET_SEED, GROUP_SEEDS["fix"], GROUP_SEEDS["rand"],
                                     GROUP_SEEDS["null_a"], GROUP_SEEDS["null_b"]])
        path = os.path.join(args.out_dir, f"{exp}_moments.npz")
        np.savez_compressed(path, **payload)
        print(f"[tvla] wrote {repo.rel(path)}")
    print(f"[tvla] finished in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
