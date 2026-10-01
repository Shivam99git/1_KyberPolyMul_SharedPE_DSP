#!/usr/bin/env python3
"""SAIF-annotated power comparison of the shared-PE and per-phase cores.

1. Common period = the largest closed period of the two cores (both meet timing there);
   read from <reports-dir>/<design>/closure_summary.csv (run the synthesis flows first).
2. Each core is simulated with the Vivado Simulator over 4 polynomial products while the
   switching activity of every net below the DUT is logged to a SAIF file:
     stimulus "manuscript": data/test_vectors/saif_manuscript (zero*zero, zero*random,
                             one*one, one*random)  -- the stimulus the manuscript used
     stimulus "random"    : data/test_vectors/saif_random      (four random operand pairs)
3. Vivado implements both cores at the common period and reports power vectorless and with
   each SAIF annotated (tags vecless_*, saif_*, saifrand_*).

Reports go to <reports-dir>/<design>/. The report records how many design nets the SAIF
matched; only a fraction does (xsim RTL net names versus the post-synthesis netlist).
Exit 3 if xsim/vivado are not available.
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
sys.path.insert(0, os.path.join(HERE, "..", "reporting"))
import repo  # noqa: E402
import vivado_parse as vp  # noqa: E402

R = repo.ROOT
DESIGNS = {"shared_pe": ("ntt_core_shared", [os.path.join(R, "rtl", "shared_pe", "ntt_core_shared.v")], []),
           "per_phase_baseline": ("ntt_core_baseline", [os.path.join(R, "rtl", "per_phase_baseline", "ntt_core_baseline.v")], [])}
COMMON = [os.path.join(R, "rtl", "common", f) for f in
          ("mod_reduce_barrett.v", "mod_addsub.v", "mult_conventional.v", "mult_unit.v", "zeta_rom.v")]
TB = os.path.join(R, "tb", "functional", "tb_polymul_functional.v")


def simulate(design, stim, nvec=4):
    top, srcs, defs = DESIGNS[design]
    bdir = os.path.join(R, "build", "saif", f"{design}_{stim}")
    shutil.rmtree(bdir, ignore_errors=True)
    os.makedirs(bdir)
    up = os.path.relpath(R, bdir)
    with open(os.path.join(bdir, "dump.tcl"), "w") as fh:
        fh.write('open_saif "activity.saif"\nlog_saif [get_objects -r /tb_polymul_functional/dut/*]\nrun all\nclose_saif\nquit\n')
    log = open(os.path.join(repo.LOG_DIR, f"saif_sim_{design}_{stim}.log"), "w")
    cmd = ["xvlog", "-sv", "-i", os.path.join(R, "rtl", "common"),
           "-d", f"ZETA_NTT_MEM=\"{up}/data/test_vectors/zetas_ntt.mem\"",
           "-d", f"ZETA_BM_MEM=\"{up}/data/test_vectors/zetas_basemul.mem\"", "-d", f"DUT={top}"] + COMMON + srcs + [TB]
    for step in (cmd, ["xelab", "tb_polymul_functional", "-s", "snap", "-debug", "typical"],
                 ["xsim", "snap", "-tclbatch", "dump.tcl", "-testplusarg", f"VEC_DIR={up}/data/test_vectors/saif_{stim}",
                  "-testplusarg", f"NUM_VEC={nvec}", "-testplusarg", "OUT=rtl_out.mem"]):
        if subprocess.run(step, cwd=bdir, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
            repo.die(f"SAIF simulation step failed: {' '.join(step[:2])} (see {repo.rel(log.name)})")
    saif = os.path.join(bdir, "activity.saif")
    if not os.path.exists(saif):
        repo.die("xsim did not write activity.saif")
    return saif


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports-dir", default=repo.REPORTS_GEN)
    args = ap.parse_args()
    for tool in ("xsim", "vivado"):
        if shutil.which(tool) is None:
            print(f"SKIPPED: required tool unavailable ({tool} not in PATH); SAIF power runs need Vivado {repo.MANUSCRIPT_VIVADO}.")
            sys.exit(3)
    repo.ensure(repo.LOG_DIR)
    periods = []
    for d in DESIGNS:
        rows = vp.read_closure(os.path.join(args.reports_dir, d, "closure_summary.csv"))
        closed = [r["period_ns"] for r in rows if r["closed"]]
        if not closed:
            repo.die(f"no closed run for {d}; run scripts/synthesis/run_{'shared_pe' if d == 'shared_pe' else 'baseline'}.tcl first")
        periods.append(min(closed))
    common = max(periods)
    print(f"[power] common closed period = {common:.3f} ns (shared {periods[0]:.3f}, per-phase {periods[1]:.3f})")

    procs = []
    for d in DESIGNS:
        env = dict(os.environ)
        env["KYBER_DESIGN"] = d
        env["KYBER_PERIOD"] = f"{common:.3f}"
        env["KYBER_REPORT_DIR"] = args.reports_dir
        for stim, var in (("manuscript", "KYBER_SAIF_MANUSCRIPT"), ("random", "KYBER_SAIF_RANDOM")):
            saif = simulate(d, stim)
            env[var] = os.path.relpath(saif, R)
            print(f"[power] {d}: SAIF ({stim} stimulus) {os.path.getsize(saif) // 1024} KiB")
        bdir = os.path.join(R, "build", "vivado", f"power_{d}")
        os.makedirs(bdir, exist_ok=True)
        log = os.path.join(repo.LOG_DIR, f"vivado_power_{d}.log")
        procs.append((d, subprocess.Popen(["vivado", "-mode", "batch", "-nojournal", "-log", log, "-source",
                                           os.path.join(R, "scripts", "power", "run_saif_power.tcl")], cwd=bdir, env=env,
                                          stdout=open(os.path.join(repo.LOG_DIR, f"vivado_power_{d}.stdout"), "w"),
                                          stderr=subprocess.STDOUT)))
    rc = 0
    for d, p in procs:
        code = p.wait()
        print(f"[{'PASS' if code == 0 else 'FAIL'}] Vivado power runs for {d}")
        rc |= code != 0
    sys.exit(1 if rc else 0)


if __name__ == "__main__":
    main()
