#!/usr/bin/env python3
"""Summarise the control-flow / memory-address invariance experiment.

Reads results/json/sim_constant_time_{shared,baseline,pipelined}.json (written by
run_rtl_sim.py from tb/constant_time/tb_constant_time.v) and reports, per design,

  A  fixed execution latency          all vectors take the same number of clock cycles
  B  invariant FSM/control trajectory FSM state, loop counters, pass selector and the
                                       multiplier start/done handshake identical every cycle
  C  invariant memory-address sequence read addresses and write enable/address identical every cycle
  D  negative control                  the data-carrying registers DO differ between inputs, so the
                                       comparison is able to detect data dependence

Writes results/json/constant_time.json and results/csv/constant_time.csv.
Exit status 1 if A, B or C does not hold, or if D shows no difference (vacuous experiment).

Scope: RTL simulation of the control-flow model. Combinational glitches, routing capacitance and
physical measurement effects are outside this experiment; it says nothing about power or
electromagnetic leakage.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402

STATEMENT = ("No data-dependent variation was observed in execution cycle count or memory-address sequence "
             "under the evaluated RTL control-flow model.")


def main():
    out, rows, bad, seen = {"statement": STATEMENT, "designs": {}}, [], 0, 0
    for key, design in (("shared", "shared_pe"), ("pipelined", "pipelined_barrett"), ("baseline", "per_phase_baseline")):
        p = os.path.join(repo.JSON_DIR, f"sim_constant_time_{key}.json")
        if not os.path.exists(p):
            print(f"[SKIPPED] constant-time, {design}: no simulation result")
            continue
        s = repo.read_json(p)
        if "vectors" not in s:
            print(f"[FAIL] constant-time, {design}: simulation did not complete")
            bad += 1
            continue
        seen += 1
        A = s["len_mismatch_vectors"] == 0 and s["unique_lengths"] == 1
        B = s["control_mismatch_vectors"] == 0 and s["unique_control_hashes"] == 1
        C = s["address_mismatch_vectors"] == 0 and s["unique_address_hashes"] == 1
        D = s["data_register_differs_in"] > 0 and s["unique_data_hashes"] > 1
        out["designs"][design] = {"vectors": s["vectors"], "latency_cycles": s["ref_len"],
                                  "A_fixed_latency": A, "B_invariant_control_trajectory": B, "C_invariant_address_sequence": C,
                                  "D_negative_control_data_differs": D, "unique_data_hashes": s["unique_data_hashes"],
                                  "control_trace_hash": s["control_trace_hash"], "address_trace_hash": s["address_trace_hash"],
                                  "source": s.get("source")}
        rows.append((design, s["vectors"], s["ref_len"], A, B, C, D, s["unique_data_hashes"], s["control_trace_hash"], s["address_trace_hash"]))
        ok = A and B and C and D
        bad += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {design:20s} vectors={s['vectors']} latency={s['ref_len']:,} cycles | "
              f"A fixed latency={A}  B control trajectory={B}  C address sequence={C}  (negative control: data registers differ in "
              f"{s['data_register_differs_in']}/{s['vectors'] - 1} vectors)")
    if seen:
        print("       " + STATEMENT)
        print("       Scope: RTL control-flow model only; glitches, routing capacitance and physical measurement effects are not covered.")
    out["status"] = "SKIPPED" if not seen and not bad else ("FAIL" if bad else "PASS")
    repo.write_json(os.path.join(repo.JSON_DIR, "constant_time.json"), out)
    repo.write_csv(os.path.join(repo.CSV_DIR, "constant_time.csv"),
                   ["design", "vectors", "latency_cycles", "A_fixed_latency", "B_invariant_control", "C_invariant_address",
                    "D_data_registers_differ", "unique_data_hashes", "control_trace_hash", "address_trace_hash"], rows)
    sys.exit(3 if out["status"] == "SKIPPED" else (1 if bad else 0))


if __name__ == "__main__":
    main()
