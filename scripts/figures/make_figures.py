#!/usr/bin/env python3
"""Regenerate every manuscript figure that is computed from project data.

Each figure is drawn only from machine-readable files written by earlier stages
(experiment -> raw data -> analysis -> figure):

  fig_cycle_breakdown   Fig. 10a  results/csv/cycle_counts.csv           (RTL cycles per phase)
  fig_area_breakdown    Fig. 10b  results/csv/hierarchy_summary.csv      (Vivado hierarchical report, 10 ns)
  fig_critical_path     Fig. 11a  results/csv/timing_summary.csv         (worst post-route path, 10 ns)
  fig_power             Fig. 11b  results/csv/power_summary.csv          (per-rail currents, 10 ns, vectorless)
  fig_slack_distribution Fig. 12  <reports>/<design>/t10p000_slacks.txt  (2000 worst endpoints per core)
  fig_tvla              Fig. 13   results/csv/tvla_shared.csv, tvla_baseline.csv
  fig_countermeasures   --        results/csv/tvla_shuffle_control.csv, tvla_shuffled.csv, tvla_masked.csv

Conceptual/architecture diagrams (block diagrams, FSM drawings, algorithm figures) are not data
plots and are not regenerated here. Outputs: results/figures/<name>.pdf and .png.
Figures whose input is missing are skipped with a message.
"""
import argparse
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402

plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 8, "axes.labelsize": 8,
                     "axes.titlesize": 8, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "legend.fontsize": 7,
                     "axes.linewidth": 0.7, "xtick.major.width": 0.7, "ytick.major.width": 0.7,
                     "pdf.fonttype": 42, "svg.hashsalt": "kyber", "pdf.compression": 6})
NAVY, ORANGE, GREEN, PURPLE = "#1f4e79", "#e07b39", "#4c9a6a", "#8d6e9e"
DESIGN_LABEL = {"per_phase_baseline": "Per-phase reference", "shared_pe": "Shared-PE", "pipelined_barrett": "Pipelined"}


def save(fig, name):
    repo.ensure(repo.FIG_DIR)
    for ext, kw in (("pdf", {}), ("png", {"dpi": 320})):
        fig.savefig(os.path.join(repo.FIG_DIR, f"{name}.{ext}"), bbox_inches="tight", pad_inches=0.02,
                    metadata={"CreationDate": None} if ext == "pdf" else None, **kw)
    plt.close(fig)
    print(f"[figures] wrote results/figures/{name}.pdf / .png")


def grouped(series, groups, ylabel, name, fmt="%.0f", colors=(NAVY, ORANGE, GREEN), pad=1.30):
    n = len(series)
    x = np.arange(len(groups))
    w = 0.8 / n
    fig, ax = plt.subplots(figsize=(3.5, 2.45))
    for i, (label, vals) in enumerate(series):
        b = ax.bar(x + (i - (n - 1) / 2) * w, vals, w * 0.92, label=label, color=colors[i], edgecolor="black", linewidth=0.55, zorder=3)
        ax.bar_label(b, fmt=fmt, padding=2, fontsize=6.3)
    ax.set_xticks(x)
    ax.set_xticklabels(groups)
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, max(max(v) for _, v in series) * pad)
    ax.yaxis.grid(True, ls=":", lw=0.5, color="0.78", zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, ncol=min(n, 3), loc="upper center", bbox_to_anchor=(0.5, 1.28), handlelength=1.3, columnspacing=1.1)
    fig.tight_layout()
    save(fig, name)


def read(name):
    p = os.path.join(repo.CSV_DIR, name)
    return repo.read_csv(p) if os.path.exists(p) else None


def fig_cycles():
    rows = read("cycle_counts.csv")
    if not rows:
        return print("[figures] fig_cycle_breakdown skipped: results/csv/cycle_counts.csv missing")
    phases = ["Forward NTT (x2)", "Pointwise multiplication", "Inverse NTT", "Final scaling"]
    by = {(r["design"], r["phase"]): r for r in rows}

    def val(design, ph):
        r = by[(design, ph)]
        return int(r["rtl_cycles"]) if r["rtl_cycles"].isdigit() else int(r["analytical_cycles"])
    grouped([("Primary ($c$=3)", [val("shared_pe", p) for p in phases]),
             ("Pipelined ($c$=4)", [val("pipelined_barrett", p) for p in phases])],
            ["Forward NTT\n($\\times$2)", "Pointwise\nmult.", "Inverse\nNTT", "Scaling"], "Clock cycles", "fig_cycle_breakdown",
            colors=(NAVY, ORANGE))


def fig_area():
    rows = read("hierarchy_summary.csv")
    if not rows:
        return print("[figures] fig_area_breakdown skipped: results/csv/hierarchy_summary.csv missing")
    groups = ["Control + storage", "Multiplier(s)", "Adder(s)", "Subtractor(s)"]

    def vals(design):
        d = {r["module_group"]: int(r["total_luts"]) for r in rows if r["design"] == design and r["role"].startswith("at_10ns")}
        return [d[g] for g in groups]
    grouped([("Per-phase reference", vals("per_phase_baseline")), ("Shared-PE", vals("shared_pe"))],
            ["Control $+$ storage\n(FSM, RAM, MUX)", "Multi-\nplier(s)", "Adder(s)", "Subtrac-\ntor(s)"], "Slice LUTs",
            "fig_area_breakdown", colors=(NAVY, GREEN))


def fig_critical_path():
    rows = read("timing_summary.csv")
    if not rows:
        return print("[figures] fig_critical_path skipped: results/csv/timing_summary.csv missing")
    d = {r["design"]: r for r in rows if r["role"].startswith("at_10ns")}
    designs = ["per_phase_baseline", "shared_pe"]
    grouped([("Total", [float(d[k]["critical_path_delay_ns"]) for k in designs]),
             ("Logic", [float(d[k]["critical_path_logic_ns"]) for k in designs]),
             ("Net", [float(d[k]["critical_path_route_ns"]) for k in designs])],
            [DESIGN_LABEL[k] for k in designs], "Critical-path delay (ns)", "fig_critical_path", fmt="%.2f", pad=1.26)


def fig_power():
    rows = read("power_summary.csv")
    if not rows:
        return print("[figures] fig_power skipped: results/csv/power_summary.csv missing")
    d = {r["design"]: r for r in rows if r["role"].startswith("at_10ns")}
    designs = ["per_phase_baseline", "shared_pe"]
    grouped([("Total", [float(d[k]["total_mw_per_rail"]) for k in designs]),
             ("Dynamic", [float(d[k]["dynamic_mw_per_rail"]) for k in designs]),
             ("Static", [float(d[k]["static_mw_per_rail"]) for k in designs])],
            [DESIGN_LABEL[k] for k in designs], "On-chip power (mW)", "fig_power", fmt="%.1f", pad=1.22)


def fig_slack():
    p = os.path.join(repo.JSON_DIR, "vivado_results.json")
    if not os.path.exists(p):
        return print("[figures] fig_slack_distribution skipped: results/json/vivado_results.json missing")
    vr = repo.read_json(p)
    fig, ax = plt.subplots(figsize=(3.98, 2.88))
    ax.grid(True, ls=":", lw=0.6, color="#cccccc")
    ax.set_axisbelow(True)
    pct = {}
    cols = {"per_phase_baseline": NAVY, "shared_pe": ORANGE, "pipelined_barrett": GREEN}
    for design in ("per_phase_baseline", "shared_pe", "pipelined_barrett"):
        d = vr["designs"].get(design)
        path = os.path.join(repo.ROOT, vr["reports_dir"], design, f"{d['at_10ns']}_slacks.txt") if d else None
        if not path or not os.path.exists(path):
            continue
        s = sorted(float(x) for x in open(path).read().split())
        xs = [v - s[0] for v in s]
        ys = [100.0 * (i + 1) / len(s) for i in range(len(s))]
        ax.plot(xs, ys, lw=1.3, color=cols[design], label=DESIGN_LABEL[design])
        pct[design] = 100.0 * sum(1 for v in xs if v <= 1.0) / len(s)
    if not pct:
        plt.close(fig)
        return print("[figures] fig_slack_distribution skipped: no slack files")
    ax.axvline(1.0, color="#808080", lw=.8, ls=":")
    for k, v in pct.items():
        ax.plot([1.0], [v], "o", ms=4, color=cols[k], zorder=5)
        ax.annotate(f"{v:.1f}%", xy=(1.0, v), xytext=(5, 3), textcoords="offset points", fontsize=7, color=cols[k])
    ax.set_xlim(0, 3.0)
    ax.set_ylim(0, 9.3)
    ax.set_xlabel("Distance from that design's own worst path (ns)")
    ax.set_ylabel("Endpoints within distance (%)")
    ax.legend(loc="upper left", frameon=False, handlelength=1.8, borderpad=.15, labelspacing=.3)
    fig.tight_layout(pad=.4)
    save(fig, "fig_slack_distribution")


def read_t(name):
    p = os.path.join(repo.CSV_DIR, name)
    if not os.path.exists(p):
        return None
    with open(p, newline="") as fh:
        r = csv.DictReader(fh)
        return np.array([float(x["t_fixed_vs_random"]) if x["t_fixed_vs_random"] else np.nan for x in r])


def fig_tvla():
    ts, tb = read_t("tvla_shared.csv"), read_t("tvla_baseline.csv")
    if ts is None or tb is None:
        return print("[figures] fig_tvla skipped: results/csv/tvla_{shared,baseline}.csv missing")
    cs = repo.read_json(os.path.join(repo.JSON_DIR, "cycle_summary.json")) if os.path.exists(os.path.join(repo.JSON_DIR, "cycle_summary.json")) else None
    # phase boundaries: cumulative Eq. (3) cycles of forward NTT, PWM, inverse NTT (c = 3)
    bounds = [14336, 14336 + 3072, 14336 + 3072 + 8064]
    fig, ax = plt.subplots(2, 1, figsize=(3.4, 2.9), sharex=True, gridspec_kw={"hspace": .18})
    for a, t, lab, col in ((ax[0], ts, "shared-PE", "#1f5fa8"), (ax[1], tb, "per-phase reference", "#b3541e")):
        a.plot(np.arange(t.size), t, lw=.25, color=col, rasterized=True)
        a.axhline(4.5, color="k", lw=.5, ls="--")
        a.axhline(-4.5, color="k", lw=.5, ls="--")
        for b in bounds:
            a.axvline(b, color="0.6", lw=.5, ls=":")
        a.set_ylabel("Welch $t$")
        a.text(.985, .90, lab, transform=a.transAxes, ha="right", va="top", fontsize=7, bbox=dict(fc="white", ec="none", alpha=.85, pad=1.2))
        lim = max(30, np.nanmax(np.abs(t)) * 1.08)
        a.set_ylim(-lim, lim)
    ax[1].set_xlabel("clock cycle")
    save(fig, "fig_tvla")


def fig_countermeasures():
    panels = [("tvla_shuffle_control.csv", "no countermeasure (matched control)", "#b3541e"),
              ("tvla_shuffled.csv", "shuffled issue order (FSM only, 1.00x latency)", "#1f7a3d"),
              ("tvla_masked.csv", "additive masking, 2 runs of the unmodified core (2.00x)", "#1f5fa8")]
    have = [(read_t(f), l, c) for f, l, c in panels if read_t(f) is not None]
    if len(have) < 2:
        return print("[figures] fig_countermeasures skipped: TVLA CSVs missing")
    fig, ax = plt.subplots(len(have), 1, figsize=(3.4, 1.05 * len(have) + .7), sharey=True, gridspec_kw={"hspace": .25})
    for a, (t, lab, col) in zip(ax, have):
        a.plot(np.arange(t.size), t, lw=.25, color=col, rasterized=True)
        a.axhline(4.5, color="k", lw=.5, ls="--")
        a.axhline(-4.5, color="k", lw=.5, ls="--")
        a.text(.985, .88, f"{lab}   max|t|={np.nanmax(np.abs(t)):.1f}", transform=a.transAxes, ha="right", va="top", fontsize=6.2,
               bbox=dict(fc="white", ec="none", alpha=.85, pad=1.2))
        a.set_ylabel("Welch $t$")
    ax[0].set_ylim(-80, 80)
    ax[-1].set_xlabel("clock cycle")
    fig.suptitle("Architecture-preserving countermeasures, shared-PE core (400 traces/group)", fontsize=7.2, y=1.005)
    save(fig, "fig_countermeasures")


FIGS = {"cycles": fig_cycles, "area": fig_area, "critical_path": fig_critical_path, "power": fig_power,
        "slack": fig_slack, "tvla": fig_tvla, "countermeasures": fig_countermeasures}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma separated subset of: " + ",".join(FIGS))
    a = ap.parse_args()
    for k in [x for x in a.only.split(",") if x] or list(FIGS):
        FIGS[k]()


if __name__ == "__main__":
    main()
