#!/usr/bin/env python3
"""Archive freshly generated evidence as the checked-in raw data (maintainer tool).

Copies, with machine-specific strings removed,
    reports/generated/vivado/**      -> reports/raw/vivado/**      (.rpt .xml .txt .csv .xdc only)
    results/logs/sim_*.log           -> reports/raw/sim/
    results/sim/<design>/rtl_out.mem, register_trace.txt  -> reports/raw/sim/*.gz
    results/tvla_raw/*.npz           -> data/tvla/

Sanitising touches only identifying strings: the absolute repository path becomes <repo>, any
remaining /home/<user> prefix becomes <home>, and the 'Host' line of Vivado banners is redacted.
No number is modified. The script refuses to write a file in which a personal path survives.

Existing archived files are never overwritten unless --force is given.
"""
import argparse
import gzip
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import repo  # noqa: E402

TEXT_EXT = (".rpt", ".xml", ".txt", ".csv", ".xdc", ".log", ".mem")


def sanitize(text):
    text = text.replace(repo.ROOT, "<repo>")
    text = re.sub(r"/home/[^/\s\"'}]+", "<home>", text)
    text = re.sub(r"(\|\s*Host\s*:\s*)(\S+)(\s+running)", r"\1<redacted>\3", text)
    text = re.sub(r"(\bHost\s*=\s*)\S+", r"\1<redacted>", text)
    return text


def leaks(text):
    user = os.environ.get("USER") or os.path.basename(os.path.expanduser("~"))
    return [p for p in ("/home/", "C:\\", user) if p and p in text]


def copy_text(src, dst, force):
    if os.path.exists(dst) and not force:
        return "exists"
    raw = open(src, errors="replace").read()
    clean = sanitize(raw)
    bad = leaks(clean)
    if bad:
        repo.die(f"{repo.rel(src)}: personal string(s) {bad} survive sanitising; not archived")
    repo.ensure(os.path.dirname(dst))
    open(dst, "w").write(clean)
    return "written"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="overwrite existing archived files")
    args = ap.parse_args()
    n = {"written": 0, "exists": 0}
    for root, _, files in os.walk(repo.REPORTS_GEN):
        for f in sorted(files):
            if f.endswith(TEXT_EXT[:5]) and not f.endswith(".log"):
                src = os.path.join(root, f)
                dst = os.path.join(repo.REPORTS_RAW, os.path.relpath(src, repo.REPORTS_GEN))
                n[copy_text(src, dst, args.force)] += 1
    for f in sorted(os.listdir(repo.LOG_DIR)) if os.path.isdir(repo.LOG_DIR) else []:
        if f.startswith("sim_") and f.endswith(".log"):
            n[copy_text(os.path.join(repo.LOG_DIR, f), os.path.join(repo.SIM_RAW, f), args.force)] += 1
    for design in ("shared_pe", "per_phase_baseline", "pipelined_barrett"):
        for stem, ext in (("rtl_out", "mem"), ("register_trace", "txt")):
            src = os.path.join(repo.SIM_DIR, design, f"{stem}.{ext}")
            dst = os.path.join(repo.SIM_RAW, f"{stem}_{design}.{ext}.gz")
            if os.path.exists(src):
                if os.path.exists(dst) and not args.force:
                    n["exists"] += 1
                    continue
                repo.ensure(os.path.dirname(dst))
                with open(src, "rb") as fi, gzip.GzipFile(dst, "wb", mtime=0) as fo:     # mtime=0: reproducible archive
                    shutil.copyfileobj(fi, fo)
                n["written"] += 1
    if os.path.isdir(repo.TVLA_GEN):
        for f in sorted(os.listdir(repo.TVLA_GEN)):
            if f.endswith(".npz"):
                dst = os.path.join(repo.TVLA_RAW, f)
                if os.path.exists(dst) and not args.force:
                    n["exists"] += 1
                    continue
                repo.ensure(repo.TVLA_RAW)
                shutil.copy(os.path.join(repo.TVLA_GEN, f), dst)
                n["written"] += 1
    print(f"[archive] {n['written']} files written, {n['exists']} already archived (use --force to overwrite)")


if __name__ == "__main__":
    main()
