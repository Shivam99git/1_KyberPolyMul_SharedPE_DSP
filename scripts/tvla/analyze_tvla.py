#!/usr/bin/env python3
"""Welch t-test analysis of the raw TVLA moment files.

Reads  <moments-dir>/<experiment>_moments.npz  (written by run_tvla.py, or the
archived copies in data/tvla/) and writes
    results/csv/tvla_shared.csv, tvla_baseline.csv, tvla_shuffled.csv,
    tvla_shuffle_control.csv, tvla_masked.csv       per-clock-cycle t values
    results/csv/tvla_multi_secret.csv              per-secret statistics
    results/json/tvla_summary.json                 every statistic quoted in the manuscript

Statistic: t = (m0 - m1) / sqrt(v0/n0 + v1/n1) with sample variances (ddof = 1),
evaluated per clock cycle. Cycles whose Hamming distance has zero variance in both
groups (control-only transitions) have no defined t and are excluded; they are
counted separately. Expected false positives = (#evaluated cycles) * P(|Z| > 4.5).
"""
import argparse
import os
import sys

import numpy as np
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402

THRESH = 4.5
P_FALSE = 2 * norm.sf(THRESH)


def load(moments_dir, exp):
    path = os.path.join(moments_dir, f"{exp}_moments.npz")
    if not os.path.exists(path):
        return None
    z = np.load(path)
    groups = {}
    for key in z.files:
        if key.endswith("__n"):
            g = key[:-3]
            groups[g] = (int(z[key]), z[f"{g}__s"].astype(np.float64), z[f"{g}__ss"].astype(np.float64))
    return groups, z["seeds"].tolist()


def welch(a, b):
    n0, s0, ss0 = a
    n1, s1, ss1 = b
    m0 = s0 / n0
    m1 = s1 / n1
    v0 = (ss0 - n0 * m0 * m0) / (n0 - 1)
    v1 = (ss1 - n1 * m1 * m1) / (n1 - 1)
    den = np.sqrt(v0 / n0 + v1 / n1)
    den[den == 0] = np.nan
    return (m0 - m1) / den


def stats(t):
    ev = np.abs(t[~np.isnan(t)])
    return {"samples": int(t.size), "cycles_evaluated": int(ev.size),
            "cycles_undefined_zero_variance": int(t.size - ev.size),
            "max_abs_t": float(ev.max()), "mean_abs_t": float(ev.mean()),
            "n_above_threshold": int((ev > THRESH).sum()),
            "pct_above_threshold": float((ev > THRESH).mean() * 100),
            "expected_false_positives": float(ev.size * P_FALSE)}


def analyse_main(groups):
    t = welch(groups["fix"], groups["rand"])
    tn = welch(groups["null_a"], groups["null_b"])
    st = stats(t)
    nst = stats(tn)
    st.update({"n_per_group": groups["fix"][0], "threshold": THRESH,
               "null_max_abs_t": nst["max_abs_t"], "null_n_above_threshold": nst["n_above_threshold"]})
    return t, tn, st


def write_trace_csv(name, t, tn):
    rows = [(i, f"{a:.9g}" if not np.isnan(a) else "", f"{b:.9g}" if not np.isnan(b) else "")
            for i, (a, b) in enumerate(zip(t, tn))]
    repo.write_csv(os.path.join(repo.CSV_DIR, name), ["cycle", "t_fixed_vs_random", "t_null"], rows)


def differing_cycle_states(idx):
    """FSM state name after the clock edge that produced each given transition sample."""
    sys.path.insert(0, HERE)
    import core_model as cm
    import random
    r = random.Random(1)
    f = [r.randrange(3329) for _ in range(256)]
    g = [r.randrange(3329) for _ in range(256)]
    c = cm.Core(True)
    c.mem_a = list(f)
    c.mem_b = list(g)
    names = []
    c.step(start_in=1)
    while c.state != cm.S["S_DONE"]:
        c.step(0)
        names.append(cm.ST[c.state])
    return [names[i] for i in idx]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--moments-dir", default=repo.TVLA_GEN,
                    help="directory with *_moments.npz (default results/tvla_raw; archived copy: data/tvla)")
    args = ap.parse_args()
    summary = {"threshold": THRESH, "p_false_positive_per_cycle": P_FALSE,
               "moments_dir": repo.rel(args.moments_dir), "experiments": {}}
    traces = {}

    for exp, csvname in (("main_shared", "tvla_shared.csv"), ("main_baseline", "tvla_baseline.csv"),
                         ("shuffle_off", "tvla_shuffle_control.csv"), ("shuffle_on", "tvla_shuffled.csv"),
                         ("masked", "tvla_masked.csv")):
        loaded = load(args.moments_dir, exp)
        if loaded is None:
            print(f"[tvla-analyze] missing {exp}_moments.npz in {repo.rel(args.moments_dir)} -- skipped")
            continue
        groups, seeds = loaded
        t, tn, st = analyse_main(groups)
        st["seeds"] = {"secret": seeds[0], "fixed_group": seeds[1], "random_group": seeds[2],
                       "null_group_a": seeds[3], "null_group_b": seeds[4]}
        summary["experiments"][exp] = st
        traces[exp] = t
        write_trace_csv(csvname, t, tn)
        print(f"[tvla-analyze] {exp:14s} n/group={st['n_per_group']} samples={st['samples']} "
              f"evaluated={st['cycles_evaluated']} max|t|={st['max_abs_t']:.2f} "
              f"above={st['n_above_threshold']} ({st['pct_above_threshold']:.2f}%) "
              f"null max|t|={st['null_max_abs_t']:.2f} chance={st['expected_false_positives']:.2f}")

    if "main_shared" in traces and "main_baseline" in traces:
        d = np.abs(traces["main_shared"] - traces["main_baseline"])
        idx = np.nonzero(d > 1e-9)[0]
        summary["shared_vs_baseline"] = {
            "cycles_where_t_traces_differ": int(idx.size),
            "of_samples": int(d.size),
            "pct_of_samples": float(idx.size / d.size * 100),
            "max_abs_t_difference": float(np.nanmax(d)),
            "differing_cycle_indices": [int(i) for i in idx],
            "fsm_state_after_edge": differing_cycle_states(idx) if idx.size else [],
            "max_abs_t_equal": bool(abs(summary["experiments"]["main_shared"]["max_abs_t"]
                                        - summary["experiments"]["main_baseline"]["max_abs_t"]) < 1e-9),
            "n_above_threshold_difference": int(abs(summary["experiments"]["main_shared"]["n_above_threshold"]
                                                    - summary["experiments"]["main_baseline"]["n_above_threshold"]))}

    # ---- five fixed secrets: corrected (random) and as originally run (constant polynomials) ----
    mrows = []
    for prefix, key in (("multi", "multi_secret"), ("multiconst", "multi_secret_constant_as_run")):
        multi = {}
        for exp in (f"{prefix}_shared", f"{prefix}_baseline"):
            loaded = load(args.moments_dir, exp)
            if loaded is None:
                continue
            groups, _ = loaded
            ts = []
            per = []
            k = 0
            while f"fix{k}" in groups:
                t = welch(groups[f"fix{k}"], groups[f"rand{k}"])
                st = stats(t)
                ts.append(t)
                per.append({"secret": k, "max_abs_t": st["max_abs_t"], "n_above_threshold": st["n_above_threshold"],
                            "cycles_evaluated": st["cycles_evaluated"], "pct": st["pct_above_threshold"]})
                mrows.append((key, exp.split("_")[1], k, groups[f"fix{k}"][0], f"{st['max_abs_t']:.6f}",
                              st["n_above_threshold"], st["cycles_evaluated"], f"{st['pct_above_threshold']:.4f}"))
                k += 1
            multi[exp] = {"n_per_group": groups["fix0"][0], "secrets": k, "per_secret": per,
                          "max_abs_t_range": [min(p["max_abs_t"] for p in per), max(p["max_abs_t"] for p in per)],
                          "pct_range": [min(p["pct"] for p in per), max(p["pct"] for p in per)], "_t": ts}
        if not multi:
            continue
        a, b = multi.get(f"{prefix}_shared"), multi.get(f"{prefix}_baseline")
        if a and b:
            multi["per_secret_trace_diff_cycles"] = [int(np.count_nonzero(np.abs(x - y) > 1e-9))
                                                     for x, y in zip(a["_t"], b["_t"])]
            multi["per_secret_leaky_count_difference"] = [
                abs(x["n_above_threshold"] - y["n_above_threshold"]) for x, y in zip(a["per_secret"], b["per_secret"])]
        for e in (a, b):
            if e:
                e.pop("_t", None)
        summary[key] = multi
        print(f"[tvla-analyze] {key}: " + ", ".join(
            f"{k.split('_')[1]}: max|t| {v['max_abs_t_range'][0]:.1f}-{v['max_abs_t_range'][1]:.1f}, "
            f"{v['pct_range'][0]:.1f}-{v['pct_range'][1]:.1f}% above" for k, v in multi.items()
            if isinstance(v, dict) and "max_abs_t_range" in v))
    if mrows:
        repo.write_csv(os.path.join(repo.CSV_DIR, "tvla_multi_secret.csv"),
                       ["secret_construction", "design", "secret", "traces_per_group", "max_abs_t",
                        "n_above_threshold", "cycles_evaluated", "pct_above_threshold"], mrows)

    repo.write_json(os.path.join(repo.JSON_DIR, "tvla_summary.json"), summary)
    print(f"[tvla-analyze] wrote {repo.rel(os.path.join(repo.JSON_DIR, 'tvla_summary.json'))}")


if __name__ == "__main__":
    main()
