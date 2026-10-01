#!/usr/bin/env python3
"""Compile and run the RTL simulations with the Vivado Simulator (xvlog/xelab/xsim).

Experiments (--only takes a comma separated list; default: all)
  functional_shared | functional_baseline | functional_pipelined
        256 vectors through each core: mismatches, latency, per-phase cycle
        breakdown, multiplier issues; RTL outputs -> results/sim/<design>/rtl_out.mem
  constant_time_shared | constant_time_baseline | constant_time_pipelined
        cycle-by-cycle control/address trajectory comparison across all vectors
  shuffled      shuffled-issue-order core, 6 LFSR seeds x 256 vectors
  masking       additive-masking protocol on the unmodified core
  barrett       exhaustive 2^24-input check of both Barrett reducers
  trace_shared | trace_baseline
        per-clock register snapshots used to validate the Python power model

Every experiment is built in build/sim/<experiment>/ (git-ignored). The simulator is
started inside that directory so all file names passed to it are relative, which keeps
the flow independent of where the repository is checked out (including paths with
spaces). Complete logs are kept in results/logs/sim_<experiment>.log and a parsed
summary in results/json/sim_<experiment>.json.

Archived mode: --from-logs DIR re-parses previously archived simulator logs (and, when present,
rtl_out_<design>.mem.gz / register_trace_<design>.txt.gz) instead of running the simulator, so the
downstream scripts can be reproduced without Vivado. DIR is normally reports/raw/sim.

Exit status 1 if any selected experiment fails; 3 if xsim is not available (SKIPPED).
"""
import argparse
import gzip
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402

R = repo.ROOT
COMMON = [os.path.join(R, "rtl", "common", f) for f in
          ("mod_reduce_barrett.v", "mod_addsub.v", "mult_conventional.v", "mult_unit.v", "zeta_rom.v")]
PIPE = [os.path.join(R, "rtl", "pipelined_barrett", f) for f in
        ("mod_reduce_barrett_pipelined.v", "mult_conventional_pipelined.v")]
SHARED = [os.path.join(R, "rtl", "shared_pe", "ntt_core_shared.v")]
SHUF = [os.path.join(R, "rtl", "shared_pe", "ntt_core_shared_shuffled.v")]
BASE = [os.path.join(R, "rtl", "per_phase_baseline", "ntt_core_baseline.v")]
TB = lambda *p: os.path.join(R, "tb", *p)  # noqa: E731

DESIGN_OF = {"shared": ("shared_pe", "ntt_core_shared", SHARED, []),
             "baseline": ("per_phase_baseline", "ntt_core_baseline", BASE, []),
             "pipelined": ("pipelined_barrett", "ntt_core_shared", SHARED + PIPE, ["USE_PIPELINED_BARRETT"])}


def experiments():
    nv = "256"
    ex = {}
    for key, (design, top, srcs, defs) in DESIGN_OF.items():
        ex[f"functional_{key}"] = dict(top="tb_polymul_functional", srcs=COMMON + srcs + [TB("functional", "tb_polymul_functional.v")],
                                       defs=defs + [f"DUT={top}"], args=[f"NUM_VEC={nv}", "OUT=rtl_out.mem"], design=design,
                                       parse="functional")
        ex[f"constant_time_{key}"] = dict(top="tb_constant_time", srcs=COMMON + srcs + [TB("constant_time", "tb_constant_time.v")],
                                          defs=defs + [f"DUT={top}"], args=[f"NUM_VEC={nv}"], design=design, parse="ct")
    ex["shuffled"] = dict(top="tb_shuffled", srcs=COMMON + SHUF + [TB("functional", "tb_shuffled.v")], defs=[],
                          args=["NUM_VEC=256"], design="shared_pe", parse="shuffled")
    ex["masking"] = dict(top="tb_masking", srcs=COMMON + SHARED + [TB("functional", "tb_masking.v")], defs=[],
                         args=["NUM_VEC=256"], design="shared_pe", parse="masking")
    ex["barrett"] = dict(top="tb_barrett_exhaustive",
                         srcs=[COMMON[0], PIPE[0], TB("barrett", "tb_barrett_exhaustive.v")], defs=[], args=[],
                         design="common", parse="barrett", debug=True)
    for key in ("shared", "baseline"):
        design, top, srcs, defs = DESIGN_OF[key]
        ex[f"trace_{key}"] = dict(top="tb_register_trace", srcs=COMMON + srcs + [TB("power", "tb_register_trace.v")],
                                  defs=defs + [f"DUT={top}"] + (["DUT_IS_BASELINE"] if key == "baseline" else []),
                                  args=["VEC_IDX=5", "OUT=register_trace.txt"], design=design, parse="trace")
    return ex


def kv(line):
    return {k: v for k, v in re.findall(r"(\w+)=(\S+)", line)}


def parse(kind, text):
    out = {}
    if kind == "functional":
        m = re.search(r"^RESULT (.*)$", text, re.M)
        p = re.search(r"^PROFILE (.*)$", text, re.M)
        if m:
            out.update({k: (int(v) if v.lstrip("-").isdigit() else v) for k, v in kv(m.group(1)).items()})
        if p:
            out["profile"] = {k: int(v) for k, v in kv(p.group(1)).items()}
        out["pass"] = "FUNCTIONAL PASS" in text and out.get("mismatches", 1) == 0
    elif kind == "ct":
        res = re.search(r"^CTRESULT (.*)$", text, re.M)
        vecs = re.findall(r"^CTVEC vec=(\d+) len=(\d+) hashB=(\w+) hashC=(\w+) hashD=(\w+) mmB=(\d+) mmC=(\d+)", text, re.M)
        if res:
            out.update({k: (int(v) if v.isdigit() else v) for k, v in kv(res.group(1)).items()})
        out["unique_lengths"] = len({v[1] for v in vecs})
        out["unique_control_hashes"] = len({v[2] for v in vecs})
        out["unique_address_hashes"] = len({v[3] for v in vecs})
        out["unique_data_hashes"] = len({v[4] for v in vecs})
        out["control_trace_hash"] = vecs[0][2] if vecs else None
        out["address_trace_hash"] = vecs[0][3] if vecs else None
        out["pass"] = bool(res) and out.get("len_mismatch_vectors", 1) == 0 and out.get("control_mismatch_vectors", 1) == 0 \
            and out.get("address_mismatch_vectors", 1) == 0 and out["unique_lengths"] == 1 \
            and out["unique_control_hashes"] == 1 and out["unique_address_hashes"] == 1
    elif kind == "shuffled":
        res = re.search(r"^SHUFRESULT (.*)$", text, re.M)
        if res:
            out.update({k: int(v) for k, v in kv(res.group(1)).items()})
        out["seed_hashes"] = dict(re.findall(r"^SHUFSEED seed=(\w+) addr_trace_hash=(\w+)", text, re.M))
        out["pass"] = ("SHUFFLED PASS" in text and out.get("mismatches", 1) == 0 and out.get("cycles_min") == out.get("cycles_max")
                       and out.get("runs_with_wrong_issue_count", 1) == 0 and out.get("runs_with_seed_trace_hash_change", 1) == 0
                       and out.get("distinct_seed_hashes") == 6)
    elif kind == "masking":
        res = re.search(r"^MASKRESULT (.*)$", text, re.M)
        if res:
            out.update({k: int(v) for k, v in kv(res.group(1)).items()})
        out["pass"] = "MASKING PASS" in text
    elif kind == "barrett":
        for line in re.findall(r"^BARRETT_RTL (.*)$", text, re.M):
            d = kv(line)
            out[d["reducer"]] = {k: int(v) for k, v in d.items() if k != "reducer"}
        out["pass"] = bool(out) and all(v["mismatches"] == 0 and v["tested"] == 2 ** 24 for v in out.values())
    elif kind == "trace":
        out["lines"] = int(re.search(r"TRACE_DONE lines=(\d+)", text).group(1)) if "TRACE_DONE" in text else 0
        out["pass"] = out["lines"] > 0
    return out


def run(cmd, cwd, log):
    log.write("$ " + " ".join(cmd).replace(R, "<repo>") + "\n")
    log.flush()
    return subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT).returncode


def finish(name, spec, text, rc, seconds, logpath, source):
    """Parse a simulator log into results/json/sim_<name>.json."""
    info = parse(spec["parse"], text) if rc == 0 else {"pass": False}
    info.update({"experiment": name, "design": spec["design"], "tool_exit_code": rc, "seconds": seconds,
                 "log": repo.rel(logpath), "source": source})
    if "ERROR" in text and rc != 0:
        info["error"] = next((l for l in text.splitlines() if "ERROR" in l), "")
    repo.write_json(os.path.join(repo.JSON_DIR, f"sim_{name}.json"), info)
    return info


def run_experiment(name, spec):
    bdir = os.path.join(R, "build", "sim", name)
    shutil.rmtree(bdir, ignore_errors=True)
    repo.ensure(bdir, repo.LOG_DIR, repo.JSON_DIR)
    up = os.path.relpath(R, bdir)
    zdefs = [f"ZETA_NTT_MEM=\"{up}/data/test_vectors/zetas_ntt.mem\"", f"ZETA_BM_MEM=\"{up}/data/test_vectors/zetas_basemul.mem\""]
    logpath = os.path.join(repo.LOG_DIR, f"sim_{name}.log")
    t0 = time.time()
    with open(logpath, "w") as log:
        cmd = ["xvlog", "-sv", "-i", os.path.join(R, "rtl", "common")]
        for d in zdefs + spec["defs"]:
            cmd += ["-d", d]
        cmd += spec["srcs"]
        rc = run(cmd, bdir, log)
        if rc == 0:
            elab = ["xelab", spec["top"], "-s", "snap"] + (["-debug", "typical"] if spec.get("debug") else [])
            rc = run(elab, bdir, log)
        if rc == 0:
            sim = ["xsim", "snap", "-R", "-testplusarg", f"VEC_DIR={up}/data/test_vectors"]
            for a in spec["args"]:
                sim += ["-testplusarg", a]
            rc = run(sim, bdir, log)
    text = open(logpath, errors="replace").read()
    info = finish(name, spec, text, rc, round(time.time() - t0, 1), logpath, "simulation run")
    for fname, kind in (("rtl_out.mem", "functional"), ("register_trace.txt", "trace")):
        if spec["parse"] == kind and os.path.exists(os.path.join(bdir, fname)):
            dst = os.path.join(repo.SIM_DIR, spec["design"])
            repo.ensure(dst)
            shutil.copy(os.path.join(bdir, fname), os.path.join(dst, fname))
    return info


def from_logs(name, spec, logdir):
    """Re-parse an archived log; restore archived RTL outputs / traces for the downstream scripts."""
    logpath = os.path.join(logdir, f"sim_{name}.log")
    if not os.path.exists(logpath):
        return None
    text = open(logpath, errors="replace").read()
    info = finish(name, spec, text, 0, 0.0, logpath, "archived log")
    for stem, ext, kind in (("rtl_out", "mem", "functional"), ("register_trace", "txt", "trace")):
        gz = os.path.join(logdir, f"{stem}_{spec['design']}.{ext}.gz")
        if spec["parse"] == kind and os.path.exists(gz):
            dst = os.path.join(repo.SIM_DIR, spec["design"])
            repo.ensure(dst)
            with gzip.open(gz, "rb") as src, open(os.path.join(dst, f"{stem}.{ext}"), "wb") as out:
                shutil.copyfileobj(src, out)
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma separated experiment names")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--from-logs", metavar="DIR", help="parse archived logs from DIR instead of running the simulator")
    args = ap.parse_args()
    ex = experiments()
    if args.list:
        print("\n".join(ex))
        return
    names = [n for n in args.only.split(",") if n] or list(ex)
    for n in names:
        if n not in ex:
            repo.die(f"unknown experiment '{n}'. Available: {', '.join(ex)}")
    if args.from_logs:
        failed = 0
        for n in names:
            info = from_logs(n, ex[n], os.path.abspath(args.from_logs))
            if info is None:
                print(f"[SKIPPED] sim {n:24s} no archived log in {repo.rel(os.path.abspath(args.from_logs))}")
                continue
            flag = "PASS" if info.get("pass") else "FAIL"
            failed += flag == "FAIL"
            print(f"[{flag}] sim {n:24s} (archived log)")
        sys.exit(1 if failed else 0)
    if shutil.which("xvlog") is None or shutil.which("xsim") is None:
        print("SKIPPED: required tool unavailable (xvlog/xelab/xsim not in PATH). Source Vivado's settings64.sh "
              "(Vivado 2024.2 was used for the manuscript) to run the RTL simulations.")
        sys.exit(3)
    failed = 0
    for n in names:
        info = run_experiment(n, ex[n])
        flag = "PASS" if info.get("pass") else "FAIL"
        failed += flag == "FAIL"
        brief = {k: v for k, v in info.items() if k in ("vectors", "coefficients", "mismatches", "cycles_min", "cycles_max",
                                                        "ref_len", "runs", "unique_control_hashes", "unique_address_hashes",
                                                        "masked_latency_min", "lines")}
        print(f"[{flag}] sim {n:24s} {info['seconds']:7.1f}s  {brief}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
