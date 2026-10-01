#!/usr/bin/env python3
"""Register-for-register validation of the Python power model against the RTL.

Inputs : results/sim/<design>/register_trace.txt  (tb/power/tb_register_trace.v, run by
         scripts/verification/run_rtl_sim.py, experiments trace_shared / trace_baseline)
         -- the value of every modelled register 1 ns after each clock edge, for vector 5
         of data/test_vectors.
Check  : scripts/tvla/core_model.py is run on the same vector; after every clock edge the
         35 (shared) / 47 (per-phase) register fields must equal the RTL values.
         A field the RTL does not reset (memory write address/data) reads 'x' until it is
         first written; those entries are skipped and counted.
Output : results/json/model_validation.json ; exit 1 on any mismatch.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import core_model as cm  # noqa: E402
import repo  # noqa: E402

VEC_IDX = 5
FIELDS_CORE = ["state", "done", "target_sel", "layer", "len_reg", "start_reg", "j_reg", "k_idx", "bm_i", "scale_idx",
               "mult_op_a", "mult_op_b", "mult_start", "wa", "wb", "wc", "wd", "w_t", "w_sum", "w_diff", "w_m1",
               "w_za1b1", "w_a0b0", "w_a0b1", "w_a1b0", "mem_a_we", "mem_a_wa", "mem_a_wd", "mem_b_we",
               "mem_b_wa", "mem_b_wd"]


def read_mem(path):
    with open(path) as fh:
        return [int(x, 16) for x in fh.read().split()]


def main():
    F = read_mem(os.path.join(repo.VECTORS, "multi_f.mem"))
    G = read_mem(os.path.join(repo.VECTORS, "multi_g.mem"))
    f, g = F[VEC_IDX * 256:(VEC_IDX + 1) * 256], G[VEC_IDX * 256:(VEC_IDX + 1) * 256]
    report = {"vector_index": VEC_IDX, "designs": {}}
    bad_total = 0
    for design, shared, label in (("shared_pe", True, "shared"), ("per_phase_baseline", False, "baseline")):
        path = os.path.join(repo.SIM_DIR, design, "register_trace.txt")
        if not os.path.exists(path):
            report["designs"][design] = {"status": "SKIPPED", "reason": "RTL register trace not generated"}
            print(f"[SKIPPED] model vs RTL, {design}: no register trace (run run_rtl_sim.py --only trace_{label})")
            continue
        rtl = [line.split() for line in open(path) if line.strip()]
        names = list(FIELDS_CORE)
        for m in range(1 if shared else 4):
            names += [f"mult{m}_state", f"mult{m}_prod_r", f"mult{m}_result", f"mult{m}_done"]
        c = cm.Core(shared)
        c.mem_a, c.mem_b = list(f), list(g)
        c.step(start_in=1)
        snaps = [c.regs()]
        while c.state != cm.S["S_DONE"]:
            c.step(0)
            snaps.append(c.regs())
        mism = skipped = compared = 0
        first = None
        if len(rtl) != len(snaps) or len(rtl[0]) != len(names):
            report["designs"][design] = {"status": "FAIL", "reason": f"shape mismatch: rtl {len(rtl)}x{len(rtl[0])} vs model {len(snaps)}x{len(names)}"}
            print(f"[FAIL] model vs RTL, {design}: shape mismatch")
            bad_total += 1
            continue
        for cyc, (row, snap) in enumerate(zip(rtl, snaps)):
            for name, rv, mv in zip(names, row, snap):
                if "x" in rv:
                    skipped += 1
                    continue
                compared += 1
                if int(rv, 16) != mv:
                    mism += 1
                    if first is None:
                        first = (cyc, name, int(rv, 16), mv)
        status = "PASS" if mism == 0 else "FAIL"
        bad_total += mism != 0
        report["designs"][design] = {"status": status, "register_fields": len(names), "clock_edges": len(snaps),
                                     "values_compared": compared, "values_skipped_unreset_x": skipped,
                                     "mismatches": mism, "first_mismatch": first}
        print(f"[{status}] model vs RTL, {design}: {len(names)} register fields x {len(snaps):,} clock edges, "
              f"{compared:,} values compared, {skipped:,} unreset (x) skipped, mismatches={mism}")
    report["status"] = "FAIL" if bad_total else ("PASS" if all(d["status"] == "PASS" for d in report["designs"].values()) else "SKIPPED")
    repo.write_json(os.path.join(repo.JSON_DIR, "model_validation.json"), report)
    sys.exit(1 if bad_total else 0)


if __name__ == "__main__":
    main()
