#!/usr/bin/env python3
"""Compare GENERATED results with the EXPECTED manuscript values.

    python3 scripts/reporting/check_manuscript_results.py [--expected data/expected/manuscript_results.json]

Expected values live only in data/expected/manuscript_results.json. Generated values are
read from results/json/*.json and results/csv/cycle_counts.csv (written by the earlier
stages). Nothing here ever copies an expected value into a generated result.

Status per check
  PASS     generated value equals the expected one (integers, booleans) or lies within the
           documented tolerance (floating-point / report-derived quantities)
  FAIL     it does not
  WARN     it does not, but the check is tool-sensitive and the reports were produced by a
           Vivado release other than 2024.2, or the check is a claim flagged for the authors
           (severity "warn"); never silently ignored
  SKIPPED  the generated value does not exist (stage not run / tool unavailable)

Exit status 1 if any check FAILs. SKIPPED and WARN do not fail the run; they are listed.
Writes results/json/manuscript_consistency.json and results/csv/manuscript_consistency.csv.
"""
import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402


def load(name):
    p = os.path.join(repo.JSON_DIR, name)
    return repo.read_json(p) if os.path.exists(p) else None


def gather():
    G = {}
    fv, bv, cs = load("functional_verification.json"), load("barrett_verification.json"), load("cycle_summary.json")
    if fv:
        rtl = fv.get("rtl", {})
        sp = rtl.get("shared_pe", {})
        G["functional"] = {
            "tests": sp.get("tests"), "coefficients": sp.get("coefficients_checked"), "mismatches": sp.get("mismatches"),
            "mismatches_baseline": rtl.get("per_phase_baseline", {}).get("mismatches"),
            "mismatches_pipelined": rtl.get("pipelined_barrett", {}).get("mismatches"),
            "reference_model_mismatches": (fv["reference_model"]["ntt_model_vs_schoolbook_mismatching_vectors"]
                                           + fv["reference_model"]["multi_h_vs_schoolbook_mismatching_vectors"]),
            "known_answer_identities_passed": sum(v == "PASS" for v in fv["known_answer_identities"].values())}
    if bv:
        sim = bv.get("rtl_simulation", {})
        G["barrett"] = {"tested_inputs": bv["tested_inputs"], "mismatches": bv["mismatches"],
                        "constants": f"K={bv['K']},M={bv['M']}",
                        "rtl_mismatches_primary": (sim.get("primary") or {}).get("mismatches"),
                        "rtl_mismatches_pipelined": (sim.get("pipelined") or {}).get("mismatches")}
    if cs:
        c = {}
        for k, d in (("primary", "shared_pe"), ("pipelined", "pipelined_barrett"), ("baseline", "per_phase_baseline")):
            c[f"rtl_{k}"] = cs[d]["rtl_total"]
            c[f"difference_{k}"] = cs[d]["difference"]
        c["mult_issues_primary"] = cs["shared_pe"].get("rtl_mult_issues")
        keymap = {"Forward NTT (x2)": "fwd_ntt", "Pointwise multiplication": "pwm", "Inverse NTT": "inv_ntt",
                  "Final scaling": "scaling", "Phase init/done": "init_done"}
        path = os.path.join(repo.CSV_DIR, "cycle_counts.csv")
        if os.path.exists(path):
            for r in repo.read_csv(path):
                grp = {"shared_pe": "phase_primary", "pipelined_barrett": "phase_pipelined"}.get(r["design"])
                if grp and r["phase"] in keymap and r["rtl_cycles"] != "SKIPPED":
                    c.setdefault(grp, {})[keymap[r["phase"]]] = int(r["rtl_cycles"])
        G["cycles"] = c
    ct = {}
    for key, d in (("shared", "shared_pe"), ("pipelined", "pipelined_barrett"), ("baseline", "per_phase_baseline")):
        s = load(f"sim_constant_time_{key}.json")
        if s and "vectors" in s:
            ct[d] = {"vectors": s["vectors"], "latency": s["ref_len"] if s["unique_lengths"] == 1 else None,
                     "length_invariant": s["len_mismatch_vectors"] == 0 and s["unique_lengths"] == 1,
                     "control_invariant": s["control_mismatch_vectors"] == 0 and s["unique_control_hashes"] == 1,
                     "address_invariant": s["address_mismatch_vectors"] == 0 and s["unique_address_hashes"] == 1}
    if ct:
        G["ct"] = ct
    dm = load("derived_metrics.json")
    if dm:
        G["derived"] = dm
        h = {d: dict(v) for d, v in dm["hierarchy"].items()}
        for d, v in h.items():
            v["addsub_instances"] = v["Adder(s)"]["instances"] + v["Subtractor(s)"]["instances"]
        G["hierarchy"] = h
    vr = load("vivado_results.json")
    if vr:
        G["timing"] = {d: v["runs"][v["at_10ns"]].get("path", {}) for d, v in vr["designs"].items()}
        G["_vivado_tool"] = vr.get("tool")
    tv = load("tvla_summary.json")
    if tv:
        t = dict(tv["experiments"])
        if "shared_vs_baseline" in tv:
            t["shared_vs_baseline"] = tv["shared_vs_baseline"]
        for src, dst in (("multi_secret_constant_as_run", "multi_asrun"), ("multi_secret", "multi_random")):
            m = tv.get(src)
            if m and "multiconst_shared" in m or m and "multi_shared" in m:
                s = m.get("multiconst_shared") or m.get("multi_shared")
                t[dst] = {"shared": {"max_t_min": s["max_abs_t_range"][0], "max_t_max": s["max_abs_t_range"][1],
                                     "pct_min": s["pct_range"][0], "pct_max": s["pct_range"][1]},
                          "trace_diff_cycles_max": max(m.get("per_secret_trace_diff_cycles", [None]))}
        G["tvla"] = t
    sh = load("shuffling_verification.json")
    if sh:
        rtl = sh.get("rtl", {})
        G["shuffling"] = {"added_flip_flops": sh["added_state"]["total_flip_flops"], "model_runs": sh["model"]["runs"],
                          "model_failures": sh["model"]["failures"], "rtl_mismatches": rtl.get("mismatches"),
                          "rtl_latency": rtl.get("cycles_min") if rtl.get("cycles_min") == rtl.get("cycles_max") else None,
                          "schedule_pairs_with_different_schedule": sh["schedule_equivalence"]["pairs_with_different_schedule"]}
    mk = load("masking_verification.json")
    if mk:
        rtl = mk.get("rtl", {})
        G["masking"] = {"model_runs": mk["model"]["masked_products"], "model_failures": mk["model"]["failures"],
                        "rtl_mismatches": rtl.get("mismatches_vs_golden"), "latency_ratio": rtl.get("latency_ratio")}
    return G


def lookup(G, key):
    cur = G
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def fmt(v):
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expected", default=repo.EXPECTED)
    ap.add_argument("--only-problems", action="store_true",
                    help="print only non-PASS checks (the complete list is always written to results/logs/manuscript_consistency.txt)")
    args = ap.parse_args()
    exp = repo.read_json(args.expected)
    G = gather()
    tool = G.get("_vivado_tool") or ""
    m = re.search(r"v\.?(\d{4}\.\d)", tool)
    detected = m.group(1) if m else None
    other_tool = detected is not None and detected != repo.MANUSCRIPT_VIVADO
    if other_tool:
        print(f"WARNING: manuscript results were generated with Vivado {repo.MANUSCRIPT_VIVADO}; the reports checked here come "
              f"from Vivado {detected}. Tool-sensitive differences are reported as WARN, not FAIL.")
    rows = []
    full_log = []
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIPPED": 0}
    for c in exp["checks"]:
        want, tol = c["expected"], c.get("tolerance", 0)
        got = lookup(G, c["key"])
        if got is None:
            status, detail = "SKIPPED", "generated value unavailable (stage not run or tool unavailable)"
        else:
            if isinstance(want, (bool, str)) or isinstance(got, (bool, str)):
                ok = got == want
            else:
                ok = abs(got - want) <= tol + 1e-12
            if ok:
                status, detail = "PASS", ""
            elif c.get("severity") == "warn":
                status, detail = "WARN", c.get("note", "")
            elif c.get("tool_sensitive") and other_tool:
                status, detail = "WARN", f"Vivado {detected} differs from {repo.MANUSCRIPT_VIVADO}"
            else:
                status, detail = "FAIL", c.get("note", "")
        counts[status] += 1
        rows.append((status, c["id"], want, got, tol, c["manuscript_ref"], c["stage"], detail, c.get("section", "")))
        line = (f"{status:7s} {c['id']:36s} expected={fmt(want):<14s} generated={fmt(got) if got is not None else '-':<14s}"
                + (f" tol={tol}" if tol and status != "SKIPPED" else "") + (f"  [{detail}]" if detail and status != "PASS" else ""))
        full_log.append(line)
        if not (args.only_problems and status == "PASS"):
            print(line)
    repo.ensure(repo.LOG_DIR)
    open(os.path.join(repo.LOG_DIR, "manuscript_consistency.txt"), "w").write("\n".join(full_log) + "\n")
    print(f"\nmanuscript consistency: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL, "
          f"{counts['SKIPPED']} SKIPPED (of {len(rows)})")
    repo.write_csv(os.path.join(repo.CSV_DIR, "manuscript_consistency.csv"),
                   ["status", "id", "expected", "generated", "tolerance", "manuscript_ref", "stage", "note", "section"], rows)
    repo.write_json(os.path.join(repo.JSON_DIR, "manuscript_consistency.json"),
                    {"counts": counts, "vivado_version_of_reports": detected, "checks": [
                        {"status": r[0], "id": r[1], "expected": r[2], "generated": r[3], "tolerance": r[4],
                         "manuscript_ref": r[5], "stage": r[6], "note": r[7], "section": r[8]} for r in rows]})
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
