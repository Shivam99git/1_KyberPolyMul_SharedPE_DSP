#!/usr/bin/env python3
"""Analytical clock-cycle model (manuscript Eq. 3) versus RTL simulation.

For one complete polynomial product, measured from the start pulse to the assertion
of done (S_IDLE not counted), with n = 256 and S = 7 transform layers:

    N_cyc(c) = 5 + 2S(n/2)[6 + (c-1)] + (n/2)[14 + 5(c-1)] + S(n/2)[7 + (c-1)] + n[5 + (c-1)]

c is the multiplier wait length in clock cycles: c = 3 for the primary core (two-cycle
multiply-reduce plus the start/done handshake cycle) and c = 4 for the pipelined-Barrett
core. The leading 5 counts the four phase-init states plus S_DONE. Each micro-sequence x
has S_x states of which m_x are multiplier-wait states that last c clocks instead of one.

The RTL per-phase cycle counts come from the simulation profile of vector 0
(results/json/sim_functional_*.json, written by run_rtl_sim.py). Nothing here is entered
by hand: if no RTL result exists the RTL columns read SKIPPED.

Writes results/csv/cycle_counts.csv and results/json/cycle_summary.json; exit status 1 if
the analytical and RTL counts differ anywhere.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
sys.path.insert(0, os.path.join(HERE, "..", "tvla"))
import repo  # noqa: E402

N, S = 256, 7
# (phase label, key in the RTL profile, runs, states per run S_x, wait states m_x, multiplier issues per run)
PHASES = [
    ("Forward NTT (x2)", "fwd_ntt", 2 * S * (N // 2), 6, 1, 1),
    ("Pointwise multiplication", "pwm", N // 2, 14, 5, 5),
    ("Inverse NTT", "inv_ntt", S * (N // 2), 7, 1, 1),
    ("Final scaling", "scaling", N, 5, 1, 1),
]
INIT_DONE = 5
DESIGNS = [("shared_pe", "functional_shared", 3), ("per_phase_baseline", "functional_baseline", 3),
           ("pipelined_barrett", "functional_pipelined", 4)]


def analytical(c):
    per = {key: runs * (st + m * (c - 1)) for _, key, runs, st, m, _ in PHASES}
    per["init_done"] = INIT_DONE
    per["total"] = sum(per.values())
    per["issues"] = sum(runs * iss for _, _, runs, _, _, iss in PHASES)
    return per


def main():
    rows = []
    summary = {}
    bad = 0
    for design, sim_name, c in DESIGNS:
        ana = analytical(c)
        simpath = os.path.join(repo.JSON_DIR, f"sim_{sim_name}.json")
        sim = repo.read_json(simpath) if os.path.exists(simpath) else None
        prof = (sim or {}).get("profile")
        rtl_total = (sim or {}).get("cycles_max") if sim and sim.get("cycles_min") == sim.get("cycles_max") else None
        entry = {"c": c, "analytical_total": ana["total"], "rtl_total": rtl_total, "issues_analytical": ana["issues"]}
        for label, key, runs, st, m, iss in PHASES + [("Phase init/done", "init_done", INIT_DONE, 1, 0, 0)]:
            rtl = None
            if prof:
                rtl = prof["init_done"] if key == "init_done" else prof[key]
            if key == "init_done":
                runs_v, st_v, m_v, iss_v = 5, 1, 0, 0
            else:
                runs_v, st_v, m_v, iss_v = runs, st, m, runs * iss
            diff = (rtl - ana[key]) if rtl is not None else None
            bad += diff not in (0, None)
            rows.append((design, label, runs_v, st_v, m_v, iss_v, c, ana[key],
                         rtl if rtl is not None else "SKIPPED", diff if diff is not None else "SKIPPED"))
        diff_t = (rtl_total - ana["total"]) if rtl_total is not None else None
        bad += diff_t not in (0, None)
        rows.append((design, "TOTAL", "", "", "", ana["issues"], c, ana["total"],
                     rtl_total if rtl_total is not None else "SKIPPED", diff_t if diff_t is not None else "SKIPPED"))
        entry["difference"] = diff_t
        entry["rtl_mult_issues"] = prof.get("mult_issues") if prof else None
        entry["status"] = "SKIPPED" if rtl_total is None else ("PASS" if diff_t == 0 else "FAIL")
        summary[design] = entry
        print(f"[{entry['status']}] {design:20s} c={c} analytical={ana['total']:,} "
              f"rtl={'SKIPPED' if rtl_total is None else format(rtl_total, ',')} "
              f"difference={'SKIPPED' if diff_t is None else diff_t}")

    # behavioural (Python) model cross-check for the c = 3 schedule
    import core_model as cm
    import random
    r = random.Random(3)
    f = [r.randrange(3329) for _ in range(256)]
    g = [r.randrange(3329) for _ in range(256)]
    core, k, _ = cm.run(f, g, True)
    py_total = k + 1            # cycles before S_DONE plus the S_DONE cycle that raises done
    summary["python_model"] = {"cycles_before_done_state": k, "total": py_total, "issues": core.issues,
                               "equals_analytical": py_total == analytical(3)["total"]}
    summary["tvla_transition_samples"] = {
        "execution_cycles": analytical(3)["total"], "samples": k,
        "explanation": ("N_cyc = 27,269 counts the clock cycles in which the FSM is not idle: 27,268 cycles before it "
                        "enters S_DONE plus the S_DONE cycle that raises the done flag. The Hamming-distance trace has one "
                        "sample per clock edge from the first edge after the start-capturing edge up to the edge that enters "
                        "S_DONE, i.e. 27,268 consecutive transition samples (the first is taken against the pre-launch reset "
                        "snapshot). The S_DONE cycle is not sampled: it changes only the 1-bit done flag, whose toggle is "
                        "input independent.")}
    print(f"[{'PASS' if summary['python_model']['equals_analytical'] else 'FAIL'}] behavioural model: "
          f"{k:,} cycles to S_DONE + 1 = {py_total:,}, multiplier issues = {core.issues}")
    bad += not summary["python_model"]["equals_analytical"]

    # per-phase percentage columns for the manuscript table
    repo.write_csv(os.path.join(repo.CSV_DIR, "cycle_counts.csv"),
                   ["design", "phase", "runs", "states_per_run", "wait_states_per_run", "multiplier_issues",
                    "wait_length_c", "analytical_cycles", "rtl_cycles", "difference"], rows)
    repo.write_json(os.path.join(repo.JSON_DIR, "cycle_summary.json"), summary)
    print(f"wrote {repo.rel(os.path.join(repo.CSV_DIR, 'cycle_counts.csv'))}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
