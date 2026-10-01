#!/usr/bin/env python3
"""Single source for every derived quantity and percentage change in the manuscript.

Inputs  (all produced by earlier stages, nothing entered by hand)
  results/json/vivado_results.json   parsed Vivado reports      (extract_results.py)
  results/json/cycle_summary.json    RTL-measured cycle counts   (cycle_model.py)
Outputs
  results/json/derived_metrics.json  unrounded values + percentage changes
  results/csv/derived_metrics.csv    the same, one row per metric

Definitions
  period / Fmax   closed period = smallest clock period at which place-and-route met timing
                  (WNS >= 0); Fmax(closed) = 1000 / period. Fmax(derived) = 1000 / (10 - WNS@10ns)
                  extrapolates from the failing 10 ns run.
  latency         cycles / f(closed)                               (scripts/timing/latency.py)
  power           per-rail supply currents of the 10 ns vectorless post-route report: each rail's
                  current x voltage, summed; dynamic and static therefore add up to the total
  energy / op     total power x latency
  ATP / DTP / EDP LUTs x latency [LUT.us], DSP48E1 x latency [DSP.us], energy x latency [nJ.s]
  change          (value - reference) / reference * 100, reference = per-phase core (Table V)
                  or primary core (Table VI)
Values are stored unrounded; the manuscript's rounding is applied only in format_tables.py.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "common"))
sys.path.insert(0, os.path.join(HERE, "..", "timing"))
import latency as lat  # noqa: E402
import repo  # noqa: E402


def pct(new, ref):
    return None if ref in (0, None) or new is None else (new - ref) / ref * 100.0


def design_metrics(d, cycles):
    runs = d["runs"]
    a10, closed = runs[d["at_10ns"]], runs[d["closed"]] if d.get("closed") else None
    u, t, px = a10["util"], a10["timing"], a10.get("power_xml", {})
    m = {"luts": u["luts"], "lut_logic": u["lut_logic"], "lut_memory": u["lut_memory"], "ffs": u["ffs"],
         "slices": u["slices"], "dsp": u["dsp"], "bram36": u["bram36"], "lut_util_pct": u["luts_util_pct"],
         "dsp_util_pct": u["dsp_util_pct"], "wns_at_10ns": t["wns"],
         "fmax_derived_mhz": 1000.0 / (10.0 - t["wns"]), "cycles": cycles,
         "critical_path_delay_ns": a10["path"]["data_path_delay"], "critical_path_logic_ns": a10["path"]["logic_delay"],
         "critical_path_route_ns": a10["path"]["route_delay"]}
    if px:
        m.update({"dynamic_mw": px["dynamic_mw"], "static_mw": px["static_mw"], "total_mw": px["total_mw"]})
    if closed:
        period = closed["period_ns"]
        f_hz = 1e9 / period
        m.update({"closed_period_ns": period, "fmax_closed_mhz": 1000.0 / period,
                  "closed_wns": closed["timing"]["wns"]})
        if cycles:
            lat_us = lat.latency_us(cycles, f_hz)
            m["latency_us"] = lat_us
            m["throughput_per_s"] = lat.throughput_per_s(lat_us)
            m["atp_lut_us"] = m["luts"] * lat_us
            m["dtp_dsp_us"] = m["dsp"] * lat_us
            if "total_mw" in m:
                m["energy_per_op_uj"] = m["total_mw"] * lat_us / 1000.0
                m["edp_nj_s"] = m["energy_per_op_uj"] * lat_us / 1000.0
    return m


def main():
    vr = repo.read_json(os.path.join(repo.JSON_DIR, "vivado_results.json"))
    cs = repo.read_json(os.path.join(repo.JSON_DIR, "cycle_summary.json"))
    out = {"designs": {}, "changes": {}, "source": {"vivado_results": vr.get("reports_dir"), "tool": vr.get("tool")}}
    for design in vr["designs"]:
        cyc = (cs.get(design) or {}).get("rtl_total")
        out["designs"][design] = design_metrics(vr["designs"][design], cyc)
    D = out["designs"]

    keys_v = ["slices", "luts", "lut_logic", "ffs", "dsp", "fmax_derived_mhz", "fmax_closed_mhz", "closed_period_ns",
              "latency_us", "throughput_per_s", "dynamic_mw", "total_mw", "energy_per_op_uj", "atp_lut_us",
              "dtp_dsp_us", "edp_nj_s"]
    if "shared_pe" in D and "per_phase_baseline" in D:
        out["changes"]["shared_vs_per_phase"] = {k: pct(D["shared_pe"].get(k), D["per_phase_baseline"].get(k)) for k in keys_v}
    if "shared_pe" in D and "pipelined_barrett" in D:
        c = {k: pct(D["pipelined_barrett"].get(k), D["shared_pe"].get(k))
             for k in ("luts", "ffs", "cycles", "closed_period_ns", "fmax_closed_mhz", "latency_us", "atp_lut_us")}
        if D["shared_pe"].get("fmax_closed_mhz"):
            c["fmax_ratio"] = D["pipelined_barrett"]["fmax_closed_mhz"] / D["shared_pe"]["fmax_closed_mhz"]
        out["changes"]["pipelined_vs_primary"] = c

    # SAIF (activity-annotated) dynamic power at the common period
    sa = {}
    for design in ("shared_pe", "per_phase_baseline"):
        d = vr["designs"].get(design, {})
        for role, key in (("saif", "saif_manuscript_stimulus"), ("saif_random_stimulus", "saif_random_stimulus"),
                          ("vecless_common", "vectorless_common_period")):
            tag = d.get(role)
            if tag and "power_xml" in d["runs"][tag]:
                sa.setdefault(key, {})[design] = {"dynamic_mw": d["runs"][tag]["power_xml"]["dynamic_mw"],
                                                  "nets_matched_pct": (d["runs"][tag].get("power_text") or {}).get("nets_matched_pct"),
                                                  "period_ns": d["runs"][tag]["period_ns"]}
    for key, v in sa.items():
        if "shared_pe" in v and "per_phase_baseline" in v:
            v["dynamic_power_change_pct"] = pct(v["shared_pe"]["dynamic_mw"], v["per_phase_baseline"]["dynamic_mw"])
    out["common_period_power"] = sa

    # hierarchical attribution (Table VIII)
    out["hierarchy"] = {}
    for design in vr["designs"]:
        d = vr["designs"][design]
        out["hierarchy"][design] = d["runs"][d["at_10ns"]].get("hier", {})

    # slack distribution statistics (Fig. 12): 2000 worst-slack endpoints of the 10 ns run, one path each
    out["slack_distribution"] = {}
    for design in vr["designs"]:
        d = vr["designs"][design]
        path = os.path.join(repo.ROOT, vr["reports_dir"], design, f"{d['at_10ns']}_slacks.txt")
        if not os.path.exists(path):
            continue
        s = sorted(float(x) for x in open(path).read().split())
        rel = [v - s[0] for v in s]
        n_within = sum(1 for v in rel if v <= 1.0)
        gaps = [b - a for a, b in zip(rel, rel[1:])]
        out["slack_distribution"][design] = {
            "endpoints": len(s), "worst_slack_ns": s[0], "endpoints_within_1ns": n_within,
            "pct_within_1ns": 100.0 * n_within / len(s),
            "gap_after_within_1ns_group_ns": gaps[n_within - 1] if n_within < len(s) else None,
            "largest_gap_ns": max(gaps)}

    repo.write_json(os.path.join(repo.JSON_DIR, "derived_metrics.json"), out)
    rows = []
    for design, m in D.items():
        rows += [(design, k, v) for k, v in sorted(m.items())]
    for grp, ch in out["changes"].items():
        rows += [(grp, k, v) for k, v in sorted(ch.items())]
    for key, v in out["common_period_power"].items():
        if "dynamic_power_change_pct" in v:
            rows.append((f"common_period_{key}", "dynamic_power_change_pct", v["dynamic_power_change_pct"]))
    repo.write_csv(os.path.join(repo.CSV_DIR, "derived_metrics.csv"), ["group", "metric", "value_unrounded"],
                   [(a, b, repr(c) if c is not None else "") for a, b, c in rows])
    print(f"[derive] wrote results/json/derived_metrics.json and results/csv/derived_metrics.csv ({len(rows)} values)")
    for design, m in D.items():
        print(f"[derive] {design:20s} LUT={m['luts']} FF={m['ffs']} DSP={m['dsp']} Fmax(closed)={m.get('fmax_closed_mhz', float('nan')):.3f} MHz "
              f"latency={m.get('latency_us', float('nan')):.3f} us")


if __name__ == "__main__":
    main()
