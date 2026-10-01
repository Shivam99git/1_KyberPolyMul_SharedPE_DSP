#!/usr/bin/env python3
"""Compare freshly generated Vivado reports with the archived raw reports (parsed values).

    python3 scripts/reporting/compare_reports.py [--generated reports/generated/vivado] [--archived reports/raw/vivado]

For every design and every run present in both directories the resource counts, WNS/TNS, critical
path delay and per-rail power are compared. With the same Vivado release, identical inputs give
identical numbers (the manuscript flows are deterministic); a difference is reported, and counts as
a failure only if both report sets were produced by the same Vivado release.
Writes results/json/report_determinism.json. Exit 3 if there is nothing to compare.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import extract_results as ex  # noqa: E402
import repo  # noqa: E402
import vivado_parse as vp  # noqa: E402


def flat(run):
    out = {}
    for sec, keys in (("util", ("luts", "lut_logic", "lut_memory", "ffs", "slices", "dsp", "bram36")),
                      ("timing", ("wns", "tns", "whs")), ("path", ("data_path_delay", "logic_delay", "route_delay", "logic_levels"))):
        for k in keys:
            out[f"{sec}.{k}"] = (run.get(sec) or {}).get(k)
    for k in ("dynamic_mw", "static_mw", "total_mw"):
        out[f"power.{k}"] = round((run.get("power_xml") or {}).get(k, float("nan")), 6)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generated", default=repo.REPORTS_GEN)
    ap.add_argument("--archived", default=repo.REPORTS_RAW)
    a = ap.parse_args()
    res, diffs, compared, tools = {}, 0, 0, set()
    for design in ex.DESIGNS:
        gd, ad = os.path.join(a.generated, design), os.path.join(a.archived, design)
        gc, ac = vp.read_closure(os.path.join(gd, "closure_summary.csv")), vp.read_closure(os.path.join(ad, "closure_summary.csv"))
        if not gc or not ac:
            continue
        common = [r["run"] for r in gc if r["run"] in {x["run"] for x in ac}]
        for tag in common:
            g = ex.collect_run(gd, tag, next(r["period_ns"] for r in gc if r["run"] == tag))
            r_ = ex.collect_run(ad, tag, next(r["period_ns"] for r in ac if r["run"] == tag))
            tools |= {(g.get("util") or {}).get("header", {}).get("tool"), (r_.get("util") or {}).get("header", {}).get("tool")}
            fg, fr = flat(g), flat(r_)
            d = {k: (fg[k], fr[k]) for k in fg if fg[k] != fr[k] and not (fg[k] != fg[k] and fr[k] != fr[k])}
            res[f"{design}/{tag}"] = {"identical": not d, "differences": d}
            compared += 1
            diffs += bool(d)
    if not compared:
        print("[SKIPPED] no common runs between generated and archived reports")
        sys.exit(3)
    tools.discard(None)
    same_tool = len({t.split(" Build")[0] for t in tools}) == 1
    status = "PASS" if diffs == 0 else ("FAIL" if same_tool else "WARN")
    repo.write_json(os.path.join(repo.JSON_DIR, "report_determinism.json"),
                    {"runs_compared": compared, "runs_with_differences": diffs, "same_vivado_release": same_tool,
                     "status": status, "details": res})
    print(f"[{status}] regenerated Vivado reports vs archived: {compared} runs compared, {diffs} with differing parsed values"
          + ("" if same_tool else " (different Vivado releases: differences are expected)"))
    sys.exit(1 if status == "FAIL" else 0)


if __name__ == "__main__":
    main()
