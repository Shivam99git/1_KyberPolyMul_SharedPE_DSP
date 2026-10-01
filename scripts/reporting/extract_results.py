#!/usr/bin/env python3
"""Parse the Vivado reports of every design into machine-readable summaries.

    python3 scripts/reporting/extract_results.py [--reports-dir reports/generated/vivado|reports/raw/vivado]

Per design (shared_pe, per_phase_baseline, pipelined_barrett) the reports directory holds
<tag>_util.rpt, <tag>_util_hier.rpt, <tag>_timing.rpt, <tag>_paths.rpt, <tag>_power.rpt,
<tag>_power.xml, <tag>_route_status.rpt, closure_summary.csv and, for the 10 ns run,
<tag>_slacks.txt  (tag = t<period with '.' -> 'p'>; SAIF/vectorless common-period runs
use the tags saif_* / vecless_*).

Run roles
  at_10ns          the common 10 ns post-route run (area/power comparisons)
  closed           the run with the smallest period that met timing (WNS >= 0)
  closure_search   every other run of the closure search
  saif / vecless   common-period power runs with and without SAIF activity

Writes results/csv/{resource,timing,power,hierarchy}_summary.csv and
results/json/vivado_results.json. Values are only parsed, never edited.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402
import vivado_parse as vp  # noqa: E402

DESIGNS = ["shared_pe", "per_phase_baseline", "pipelined_barrett"]


def tag_period(tag):
    return float(tag[1:].replace("p", ".")) if tag.startswith("t") else None


def collect_run(ddir, tag, period=None):
    pfx = os.path.join(ddir, tag)
    run = {"tag": tag, "period_ns": period}
    if os.path.exists(pfx + "_util.rpt"):
        run["util"] = vp.parse_utilization(pfx + "_util.rpt")
    if os.path.exists(pfx + "_timing.rpt"):
        run["timing"] = vp.parse_timing_summary(pfx + "_timing.rpt")
    if os.path.exists(pfx + "_paths.rpt"):
        run["path"] = vp.parse_paths(pfx + "_paths.rpt")
    if os.path.exists(pfx + "_power.rpt"):
        run["power_text"] = vp.parse_power_text(pfx + "_power.rpt")
    if os.path.exists(pfx + "_power.xml"):
        run["power_xml"] = vp.parse_power_xml(pfx + "_power.xml")
    if os.path.exists(pfx + "_route_status.rpt"):
        run["route"] = vp.parse_route_status(pfx + "_route_status.rpt")
    if os.path.exists(pfx + "_util_hier.rpt"):
        run["hier"] = vp.parse_hier(pfx + "_util_hier.rpt")
    if os.path.exists(pfx + "_slacks.txt"):
        run["slack_endpoints"] = len(vp.read_slacks(pfx + "_slacks.txt"))
    wns = run.get("timing", {}).get("wns")
    if period and wns is not None:
        run["fmax_derived_mhz"] = 1000.0 / (period - wns)
        run["closed"] = wns >= 0
        run["fmax_closed_mhz"] = 1000.0 / period if wns >= 0 else None
    return run


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports-dir", default=repo.REPORTS_GEN)
    args = ap.parse_args()
    out = {"reports_dir": repo.rel(args.reports_dir), "designs": {}}
    res_rows, tim_rows, pow_rows, hier_rows = [], [], [], []
    tool = None
    for design in DESIGNS:
        ddir = os.path.join(args.reports_dir, design)
        if not os.path.isdir(ddir):
            continue
        closure = vp.read_closure(os.path.join(ddir, "closure_summary.csv"))
        if not closure:
            continue
        runs, roles = {}, {}
        for c in closure:
            runs[c["run"]] = collect_run(ddir, c["run"], c["period_ns"])
            roles[c["run"]] = "closure_search"
        at10 = next(c["run"] for c in closure if abs(c["period_ns"] - 10.0) < 1e-9)
        closed_rows = [c for c in closure if c["closed"]]
        closed = min(closed_rows, key=lambda c: c["period_ns"])["run"] if closed_rows else None
        roles[at10] = "at_10ns"
        if closed:
            roles[closed] = "closed" if closed != at10 else "at_10ns+closed"
        extra = {}
        for tag in sorted(f[:-len("_power.xml")] for f in os.listdir(ddir) if f.endswith("_power.xml")):
            if tag.startswith(("saif_", "saifrand_", "vecless_")):
                period = tag_period("t" + tag.split("_t", 1)[1]) if "_t" in tag else None
                runs[tag] = collect_run(ddir, tag, period)
                roles[tag] = {"saif": "saif", "saifrand": "saif_random_stimulus",
                              "vecless": "vecless_common"}[tag.split("_")[0]]
                extra[roles[tag]] = tag
        for tag, run in runs.items():
            run["role"] = roles[tag]
            hdr = (run.get("util") or {}).get("header") or {}
            tool = tool or hdr.get("tool")
        entry = {"runs": runs, "at_10ns": at10, "closed": closed, "closure_search": [c["run"] for c in closure]}
        entry.update(extra)
        out["designs"][design] = entry

        for tag, run in runs.items():
            u, t, pth, px, pt, rt = (run.get(k, {}) for k in ("util", "timing", "path", "power_xml", "power_text", "route"))
            res_rows.append((design, tag, run["role"], run["period_ns"], u.get("luts"), u.get("lut_logic"), u.get("lut_memory"),
                             u.get("ffs"), u.get("slices"), u.get("dsp"), u.get("bram36"), u.get("ramb18"),
                             u.get("luts_util_pct"), u.get("ffs_util_pct"), u.get("slices_util_pct"), u.get("dsp_util_pct")))
            tim_rows.append((design, tag, run["role"], run["period_ns"], t.get("wns"), t.get("tns"), t.get("whs"),
                             t.get("tns_failing_endpoints"), run.get("closed"),
                             f"{run['fmax_derived_mhz']:.4f}" if run.get("fmax_derived_mhz") else "",
                             f"{run['fmax_closed_mhz']:.4f}" if run.get("fmax_closed_mhz") else "",
                             pth.get("data_path_delay"), pth.get("logic_delay"), pth.get("route_delay"),
                             pth.get("logic_levels"), pth.get("source"), pth.get("destination"), rt.get("routing_errors"),
                             rt.get("unrouted")))
            if pt or px:
                pow_rows.append((design, tag, run["role"], run["period_ns"], pt.get("activity_file"), pt.get("confidence"),
                                 pt.get("nets_matched_pct"), pt.get("total_w"), pt.get("dynamic_w"), pt.get("static_w"),
                                 f"{px['total_mw']:.4f}" if px else "", f"{px['dynamic_mw']:.4f}" if px else "",
                                 f"{px['static_mw']:.4f}" if px else ""))
            for g, v in (run.get("hier") or {}).items():
                hier_rows.append((design, tag, run["role"], g, v["luts"], v["logic_luts"], v["lutram"], v["ffs"], v["dsp"], v["instances"]))
        print(f"[extract] {design}: {len(runs)} runs, at_10ns={at10}, closed={closed}")

    if not out["designs"]:
        repo.die(f"no Vivado reports found under {repo.rel(args.reports_dir)} (run the flows, or use --reports-dir reports/raw)")
    out["tool"] = tool
    repo.write_csv(os.path.join(repo.CSV_DIR, "resource_summary.csv"),
                   ["design", "run", "role", "period_ns", "slice_luts", "lut_as_logic", "lut_as_memory", "slice_registers",
                    "occupied_slices", "dsp48e1", "bram36_tiles", "ramb18", "lut_util_pct", "ff_util_pct", "slice_util_pct",
                    "dsp_util_pct"], res_rows)
    repo.write_csv(os.path.join(repo.CSV_DIR, "timing_summary.csv"),
                   ["design", "run", "role", "period_ns", "wns_ns", "tns_ns", "whs_ns", "failing_setup_endpoints", "met_timing",
                    "fmax_derived_mhz", "fmax_closed_mhz", "critical_path_delay_ns", "critical_path_logic_ns",
                    "critical_path_route_ns", "logic_levels", "critical_source", "critical_destination", "routing_errors",
                    "unrouted_nets"], tim_rows)
    repo.write_csv(os.path.join(repo.CSV_DIR, "power_summary.csv"),
                   ["design", "run", "role", "period_ns", "activity", "confidence", "nets_matched_pct", "total_w_report",
                    "dynamic_w_report", "static_w_report", "total_mw_per_rail", "dynamic_mw_per_rail", "static_mw_per_rail"], pow_rows)
    repo.write_csv(os.path.join(repo.CSV_DIR, "hierarchy_summary.csv"),
                   ["design", "run", "role", "module_group", "total_luts", "logic_luts", "lutram", "ffs", "dsp48e1", "instances"],
                   hier_rows)
    repo.write_json(os.path.join(repo.JSON_DIR, "vivado_results.json"), out)
    print(f"[extract] tool: {tool}")
    print("[extract] wrote results/csv/{resource,timing,power,hierarchy}_summary.csv and results/json/vivado_results.json")


if __name__ == "__main__":
    main()
