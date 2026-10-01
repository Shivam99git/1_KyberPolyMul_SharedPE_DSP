#!/usr/bin/env python3
"""Write results/reproduction_metadata.json (no usernames, hostnames or private paths).

Records: git commit, date, Python / package versions, Vivado and simulator versions, FPGA part,
every random seed used by an experiment, the reproduce_all.sh arguments and mode, and where each
stage's evidence came from (regenerated in this run vs archived). Stage results are read from
results/stage_status.tsv, written by reproduce_all.sh.
"""
import argparse
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
sys.path.insert(0, os.path.join(HERE, "..", "tvla"))
import repo  # noqa: E402


def pkg(name):
    try:
        return __import__(name).__version__
    except Exception:  # noqa: BLE001
        return "not installed"


def seeds():
    import run_tvla as rt
    sys.path.insert(0, os.path.join(HERE, "..", "verification"))
    import gen_test_vectors as gv
    return {
        "test_vectors": {"random_pairs": gv.SEED_RANDOM, "corner_case_random_polynomial": gv.SEED_CORNER_R,
                         "directed_example": gv.SEED_DIRECTED, "masking_f1": gv.SEED_MASK},
        "tvla": {"fixed_secret": rt.SECRET_SEED, "group_seeds": rt.GROUP_SEEDS,
                 "multi_secret_base": rt.MULTI_SECRET_SEED_BASE, "multi_group_base": rt.MULTI_GROUP_SEED_BASE},
        "shuffling_lfsr_seeds": ["0xACE12345", "0x00000001", "0xFFFFFFFF", "0xDEADBEEF", "0x5A5A5A5A", "0x13579BDF"],
        "masking_model": {"operand_seed": 2024, "mask_seeds": [1000, 1001, 1002, 1003, 1004]},
        "shuffling_model": {"vector_seed": 31337},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", default="")
    ap.add_argument("--args", default="")
    a = ap.parse_args()
    env = repo.environment()
    env.update({"numpy": pkg("numpy"), "scipy": pkg("scipy"), "matplotlib": pkg("matplotlib"),
                "os": platform.system() + " " + platform.release().split("-")[0]})
    stages = []
    p = os.path.join(repo.RESULTS, "stage_status.tsv")
    if os.path.exists(p):
        for line in open(p).read().splitlines():
            n, name, status, secs, source, note = (line.split("\t") + [""] * 6)[:6]
            stages.append({"stage": int(n), "name": name, "status": status, "seconds": float(secs or 0), "evidence": source, "note": note})
    meta = {"generated_utc": repo.utc_now(), "mode": a.mode, "command_line_arguments": a.args,
            "manuscript_tool_version": f"Vivado {repo.MANUSCRIPT_VIVADO}", "fpga_part": repo.FPGA_PART,
            "environment": env, "seeds": seeds(), "stages": stages}
    repo.write_json(os.path.join(repo.RESULTS, "reproduction_metadata.json"), meta)
    print("[metadata] wrote results/reproduction_metadata.json")


if __name__ == "__main__":
    main()
