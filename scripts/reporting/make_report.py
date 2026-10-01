#!/usr/bin/env python3
"""Assemble results/REPRODUCIBILITY_REPORT.md from the generated results.

Every line is read from results/json, results/csv or results/stage_status.tsv; nothing is typed
in. Each section states PASS / FAIL / SKIPPED, whether the evidence was regenerated in this run
or taken from the archived raw data, and where the evidence is.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402


def j(name):
    p = os.path.join(repo.JSON_DIR, name)
    return repo.read_json(p) if os.path.exists(p) else None


def n(v, d=0):
    return "n/a" if v is None else (f"{v:,.{d}f}" if isinstance(v, (int, float)) else str(v))


def check_status(cons, section):
    rows = [c for c in (cons or {}).get("checks", []) if c.get("section") == section]
    if not rows:
        return "SKIPPED", 0, 0
    st = [c["status"] for c in rows]
    if "FAIL" in st:
        return "FAIL", st.count("PASS"), len(rows)
    if all(s == "SKIPPED" for s in st):
        return "SKIPPED", 0, len(rows)
    if "WARN" in st:
        return "WARN", st.count("PASS"), len(rows)
    return ("PASS" if "SKIPPED" not in st else "PARTIAL"), st.count("PASS"), len(rows)


def src_of(path):
    if path is None:
        return "n/a"
    return "archived raw data" if ("reports/raw" in path or "data/tvla" in path or path.startswith("archived")) else "regenerated in this run"


def main():
    cons = j("manuscript_consistency.json")
    meta = j("reproduction_metadata.json") or {}
    env = meta.get("environment", {})
    L = ["# Reproducibility Report", "",
         f"Generated: {meta.get('generated_utc', 'n/a')}  |  mode: `{meta.get('mode', 'n/a')}`  |  arguments: `{meta.get('command_line_arguments', '')}`", ""]

    L += ["## Environment", ""]
    vv = env.get("vivado", "not found")
    L += [f"- Python {env.get('python')} (numpy {env.get('numpy')}, scipy {env.get('scipy')}, matplotlib {env.get('matplotlib')}), {env.get('os')}",
          f"- Vivado (local): {vv}; manuscript results were generated with Vivado {repo.MANUSCRIPT_VIVADO}",
          f"- FPGA part: {env.get('fpga_part')}  |  git commit: {env.get('git_commit')}"]
    if vv != "not found" and repo.MANUSCRIPT_VIVADO not in vv:
        L.append(f"- **WARNING**: local Vivado is not {repo.MANUSCRIPT_VIVADO}; regenerated FPGA numbers may differ from the manuscript.")
    L += ["", "| # | Stage | Status | Evidence | Seconds |", "|--:|---|---|---|--:|"]
    for s in meta.get("stages", []):
        L.append(f"| {s['stage']} | {s['name']} | {s['status']} | {s['evidence']} | {s['seconds']:.0f} |")
    L.append("")

    fv = j("functional_verification.json")
    L += ["## Functional Verification", ""]
    if fv:
        st = fv["status"]
        L.append(f"**{st}** -- software reference model (NTT model vs independent schoolbook vs stored golden output): "
                 f"{fv['reference_model']['vectors']} vectors, {fv['reference_model']['coefficients']:,} coefficients, "
                 f"mismatches = {fv['reference_model']['ntt_model_vs_schoolbook_mismatching_vectors'] + fv['reference_model']['multi_h_vs_schoolbook_mismatching_vectors']}.")
        L += ["", "| Design | tests | coefficients checked | RTL vs schoolbook mismatches | status |", "|---|--:|--:|--:|---|"]
        for d, r in fv["rtl"].items():
            L.append(f"| {d} | {n(r.get('tests'))} | {n(r.get('coefficients_checked'))} | {n(r.get('mismatches'))} | {r['status']} |")
        L.append("")
        L.append(f"Evidence: `results/json/functional_verification.json`, `results/csv/functional_verification.csv`, RTL outputs `results/sim/*/rtl_out.mem`.")
    else:
        L.append("**SKIPPED** -- results/json/functional_verification.json not generated.")
    L.append("")

    bv = j("barrett_verification.json")
    L += ["## Barrett Verification", ""]
    if bv:
        rtl = bv["rtl_simulation"]
        L.append(f"**{bv['status']}** -- q={bv['q']}, K={bv['K']}, M={bv['M']}: {bv['tested_inputs']:,} inputs "
                 f"(min {bv['min_input']}, max {bv['max_input']}), mismatches = {bv['mismatches']}; largest pre-correction remainder "
                 f"{bv['max_pre_correction_remainder']} < 2q = {2 * bv['q']} (one conditional subtraction always suffices).")
        L.append(f"RTL simulation of both reducers over the same inputs: **{rtl['status']}**"
                 + (f" (primary mismatches {rtl['primary']['mismatches']}, pipelined {rtl['pipelined']['mismatches']})" if rtl.get('primary') else "") + ".")
        L.append("\nEvidence: `results/json/barrett_verification.json`, `results/logs/sim_barrett.log`.")
    else:
        L.append("**SKIPPED**")
    L.append("")

    cs = j("cycle_summary.json")
    L += ["## Cycle Counts", ""]
    if cs:
        L += ["| Design | wait length c | analytical (Eq. 3) | RTL | difference | status |", "|---|--:|--:|--:|--:|---|"]
        for d in ("shared_pe", "per_phase_baseline", "pipelined_barrett"):
            e = cs[d]
            L.append(f"| {d} | {e['c']} | {n(e['analytical_total'])} | {n(e['rtl_total'])} | {n(e['difference'])} | {e['status']} |")
        L += ["", f"Behavioural Python model: {cs['python_model']['total']:,} cycles, {cs['python_model']['issues']} multiplier issues. "
              f"Trace samples: {cs['tvla_transition_samples']['samples']:,}.", "", "Evidence: `results/csv/cycle_counts.csv`, `results/json/cycle_summary.json`."]
    else:
        L.append("**SKIPPED**")
    L.append("")

    vr, dm = j("vivado_results.json"), j("derived_metrics.json")
    vsrc = src_of(vr["reports_dir"]) if vr else "n/a"
    for title, sec in (("FPGA Resources", "resources"), ("Timing", "timing"), ("Power", "power")):
        st, ok, tot = check_status(cons, sec)
        L += [f"## {title}", ""]
        if not (vr and dm):
            L += ["**SKIPPED** -- no Vivado reports available (run with Vivado, or use `--from-reports`).", ""]
            continue
        L.append(f"**{st}** ({ok}/{tot} checks against the manuscript pass) -- evidence: {vsrc} (`{vr['reports_dir']}`), tool: {vr.get('tool')}.")
        D = dm["designs"]
        if sec == "resources":
            L += ["", "| Design (10 ns, post-route) | LUT | LUT logic | LUT mem | FF | slices | DSP48E1 | BRAM |", "|---|--:|--:|--:|--:|--:|--:|--:|"]
            for d in ("shared_pe", "per_phase_baseline", "pipelined_barrett"):
                if d in D:
                    m = D[d]
                    L.append(f"| {d} | {m['luts']} | {m['lut_logic']} | {m['lut_memory']} | {m['ffs']} | {m['slices']} | {m['dsp']} | {m['bram36']} |")
        elif sec == "timing":
            L += ["", "| Design | WNS@10 ns | Fmax derived (MHz) | closed period (ns) | Fmax closed (MHz) | cycles | latency (us) |", "|---|--:|--:|--:|--:|--:|--:|"]
            for d in ("shared_pe", "per_phase_baseline", "pipelined_barrett"):
                if d in D:
                    m = D[d]
                    L.append(f"| {d} | {m['wns_at_10ns']:.3f} | {m['fmax_derived_mhz']:.2f} | {n(m.get('closed_period_ns'), 3)} | "
                             f"{n(m.get('fmax_closed_mhz'), 2)} | {n(m.get('cycles'))} | {n(m.get('latency_us'), 2)} |")
        else:
            L += ["", "| Design (10 ns vectorless) | dynamic (mW) | static (mW) | total (mW) | energy/op (uJ) |", "|---|--:|--:|--:|--:|"]
            for d in ("shared_pe", "per_phase_baseline", "pipelined_barrett"):
                if d in D and "total_mw" in D[d]:
                    m = D[d]
                    L.append(f"| {d} | {m['dynamic_mw']:.3f} | {m['static_mw']:.3f} | {m['total_mw']:.3f} | {n(m.get('energy_per_op_uj'), 2)} |")
            sp = dm.get("common_period_power", {})
            for key, v in sp.items():
                if "dynamic_power_change_pct" in v:
                    nets = v["shared_pe"].get("nets_matched_pct")
                    L.append(f"\n- {key}: shared-PE {v['shared_pe']['dynamic_mw']:.3f} mW vs per-phase {v['per_phase_baseline']['dynamic_mw']:.3f} mW at "
                             f"{v['shared_pe']['period_ns']} ns -> {v['dynamic_power_change_pct']:+.1f} %"
                             + (f" (SAIF matched {nets:.0f} % / {v['per_phase_baseline']['nets_matched_pct']:.0f} % of design nets)" if nets else ""))
        L += ["", "Evidence: `results/csv/{resource,timing,power,hierarchy}_summary.csv`, `results/json/derived_metrics.json`.", ""]

    ct = j("constant_time.json")
    L += ["## Constant-Time Verification", ""]
    if ct and ct["designs"]:
        L.append(f"**{ct['status']}** -- {ct['statement']}")
        L += ["", "| Design | vectors | latency (cycles) | A fixed latency | B control trajectory | C address sequence | negative control (data registers differ) |", "|---|--:|--:|---|---|---|---|"]
        for d, e in ct["designs"].items():
            L.append(f"| {d} | {e['vectors']} | {e['latency_cycles']:,} | {e['A_fixed_latency']} | {e['B_invariant_control_trajectory']} | {e['C_invariant_address_sequence']} | {e['D_negative_control_data_differs']} |")
        L += ["", "Scope: RTL control-flow model. Combinational glitches, routing capacitance and physical measurement effects are outside this experiment; no claim of physical side-channel resistance is made.",
              "", "Evidence: `results/json/constant_time.json`, `results/csv/constant_time.csv`, `results/logs/sim_constant_time_*.log`."]
    else:
        L.append("**SKIPPED**")
    L.append("")

    tv = j("tvla_summary.json")
    L += ["## TVLA", ""]
    if tv:
        st, ok, tot = check_status(cons, "tvla")
        L.append(f"**{st}** ({ok}/{tot}) -- simulated, register-level Hamming-distance model, fixed-vs-random Welch t-test, threshold |t| > {tv['threshold']}; "
                 f"evidence: {src_of(tv['moments_dir'])} (`{tv['moments_dir']}`).")
        L += ["", "| Experiment | traces/group | samples | evaluated | max abs t | cycles above | expected by chance | null max abs t |", "|---|--:|--:|--:|--:|--:|--:|--:|"]
        for k, e in tv["experiments"].items():
            L.append(f"| {k} | {e['n_per_group']} | {e['samples']:,} | {e['cycles_evaluated']:,} | {e['max_abs_t']:.2f} | {e['n_above_threshold']} ({e['pct_above_threshold']:.2f} %) | {e['expected_false_positives']:.2f} | {e['null_max_abs_t']:.2f} |")
        sb = tv.get("shared_vs_baseline")
        if sb:
            L.append(f"\nShared-PE vs per-phase t-traces differ in {sb['cycles_where_t_traces_differ']} of {sb['of_samples']:,} cycles "
                     f"({sb['pct_of_samples']:.3f} %), largest discrepancy {sb['max_abs_t_difference']:.2f}, FSM states {sorted(set(sb['fsm_state_after_edge']))}.")
        for key, label in (("multi_secret_constant_as_run", "five fixed secrets AS ORIGINALLY RUN (each secret a constant polynomial)"),
                           ("multi_secret", "five independent RANDOM fixed secrets (corrected)")):
            m = tv.get(key, {})
            e = m.get("multiconst_shared") or m.get("multi_shared")
            if e:
                L.append(f"\n- {label}: max|t| {e['max_abs_t_range'][0]:.1f} - {e['max_abs_t_range'][1]:.1f}, "
                         f"{e['pct_range'][0]:.1f} - {e['pct_range'][1]:.1f} % of cycles above threshold.")
        L += ["", "These are pre-silicon simulation results, not physical power measurements.", "",
              "Evidence: `results/json/tvla_summary.json`, `results/csv/tvla_*.csv`, `results/figures/fig_tvla.pdf`."]
    else:
        L.append("**SKIPPED**")
    L.append("")

    mk = j("masking_verification.json")
    L += ["## Masking", ""]
    if mk:
        r = mk["rtl"]
        L.append(f"**{mk['status']}** -- model: {mk['model']['masked_products']} masked products, failures {mk['model']['failures']}; "
                 f"RTL core(f1,g)+core(f2,g)==core(f,g): {r['status']}" + (f" ({r['vectors']} vectors, mismatches {r['mismatches_vs_golden']})" if r['status'] != 'SKIPPED' else "")
                 + f"; latency {mk['latency']['ratio']:.2f}x.")
        t = (mk.get("tvla") or {})
        if t:
            L.append(f"\nTVLA of the masked protocol ({t['n_per_group']} traces/group): max|t| = {t['max_abs_t']:.2f}, {t['n_above_threshold']} of {t['cycles_evaluated']:,} cycles above threshold "
                     f"(chance {t['expected_false_positives']:.2f}), null max|t| {t['null_max_abs_t']:.2f}. First-order protection under the evaluated register-level model only; "
                     "higher-order and glitch-extended leakage are outside this experiment.")
        L.append("\nEvidence: `results/json/masking_verification.json`, `results/json/tvla_summary.json`.")
    else:
        L.append("**SKIPPED**")
    L.append("")

    sh = j("shuffling_verification.json")
    L += ["## Shuffling", ""]
    if sh:
        se, md, rt = sh["schedule_equivalence"], sh["model"], sh["rtl"]
        L.append(f"**{sh['status']}** -- schedule equivalence over {se['ntt_intt_start_stride_pairs_checked']:,} (start, stride) pairs: {se['pairs_with_different_schedule']} differ; "
                 f"model {md['runs']} runs, failures {md['failures']}, cycles unchanged; RTL: {rt['status']}"
                 + (f" ({rt['runs']} runs, mismatches {rt['mismatches']}, latency {rt['cycles_min']})" if rt['status'] != 'SKIPPED' else "")
                 + f"; permutation state {sh['added_state']['total_flip_flops']} flip-flops (declared).")
        tl = sh.get("tvla")
        if tl:
            L.append(f"\nTVLA (400 traces/group): matched control max|t| {tl['matched_control']['max_abs_t']:.1f} ({tl['matched_control']['n_above_threshold']} cycles above) -> "
                     f"shuffled max|t| {tl['shuffled']['max_abs_t']:.1f} ({tl['shuffled']['n_above_threshold']} of {tl['shuffled']['cycles_evaluated']:,}, chance {tl['shuffled']['expected_false_positives']:.2f}). "
                     "Shuffling is a hiding countermeasure: residual first-order leakage remains and its benefit depends on the trace count.")
        L.append("\nEvidence: `results/json/shuffling_verification.json`.")
    else:
        L.append("**SKIPPED**")
    L.append("")

    L += ["## Manuscript Consistency", ""]
    if cons:
        c = cons["counts"]
        L.append(f"**{'FAIL' if c['FAIL'] else 'PASS'}** -- {c['PASS']} PASS, {c['WARN']} WARN, {c['FAIL']} FAIL, {c['SKIPPED']} SKIPPED "
                 f"of {sum(c.values())} checks (`data/expected/manuscript_results.json` vs generated).")
        nonpass = [x for x in cons["checks"] if x["status"] in ("FAIL", "WARN")]
        if nonpass:
            L += ["", "| Status | Check | Expected | Generated | Note |", "|---|---|--:|--:|---|"]
            for x in nonpass:
                L.append(f"| {x['status']} | {x['id']} | {x['expected']} | {x['generated']} | {x['note']} |")
        skipped = [x["id"] for x in cons["checks"] if x["status"] == "SKIPPED"]
        if skipped:
            L.append(f"\nSKIPPED checks ({len(skipped)}): generated value unavailable -- " + ", ".join(skipped[:12]) + (" ..." if len(skipped) > 12 else ""))
        L.append("\nEvidence: `results/csv/manuscript_consistency.csv`, `results/json/manuscript_consistency.json`.")
    else:
        L.append("**SKIPPED**")
    L.append("")
    out = os.path.join(repo.RESULTS, "REPRODUCIBILITY_REPORT.md")
    open(out, "w").write("\n".join(L))
    print(f"[report] wrote {repo.rel(out)}")


if __name__ == "__main__":
    main()
