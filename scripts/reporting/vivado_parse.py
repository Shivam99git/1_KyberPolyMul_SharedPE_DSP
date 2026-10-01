"""Parsers for Vivado 2024.2 text/XML reports. Everything is extracted with regular
expressions from the report files themselves; no value is entered by hand."""
import csv
import os
import re
import xml.etree.ElementTree as ET


def _read(path):
    with open(path, errors="replace") as fh:
        return fh.read()


def _num(s):
    s = s.strip()
    return float(s) if re.fullmatch(r"-?\d+\.\d+|-?\d+", s) else None


def parse_header(text):
    """Tool/device fields of the report banner (host and command lines are ignored)."""
    out = {}
    for key, pat in (("tool", r"\| Tool Version\s*:\s*(.+)"), ("device", r"\| Device\s*:\s*(\S+)"),
                     ("design", r"\| Design\s*:\s*(\S+)"), ("state", r"\| Design State\s*:\s*(.+)")):
        m = re.search(pat, text)
        out[key] = m.group(1).strip() if m else None
    return out


def parse_utilization(path):
    t = _read(path)

    def row(label, col=1):
        m = re.search(r"\|\s*" + label + r"\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.<]+)\s*\|", t)
        return m
    res = {"header": parse_header(t)}
    for key, label in (("luts", r"Slice LUTs\*?"), ("lut_logic", r"LUT as Logic"), ("lut_memory", r"LUT as Memory"),
                       ("ffs", r"Slice Registers"), ("slices", r"Slice"), ("dsp", r"DSPs"),
                       ("bram36", r"Block RAM Tile"), ("ramb36", r"RAMB36/FIFO\*?"), ("ramb18", r"RAMB18")):
        m = row(label)
        if m:
            res[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
            res[key + "_available"] = float(m.group(4)) if m.group(4) else None
            res[key + "_util_pct"] = float(m.group(5).replace("<", "")) if m.group(5) else None
    for k in ("luts", "lut_logic", "lut_memory", "ffs", "slices", "dsp", "ramb36", "ramb18"):
        if k in res:
            res[k] = int(res[k])
    return res


def parse_timing_summary(path):
    t = _read(path)
    res = {"header": parse_header(t)}
    m = re.search(r"\| Design Timing Summary\s*\n.*\n-+\s*\n\s*\n\s*WNS\(ns\).*\n\s*-+.*\n\s*([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+"
                  r"([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)", t)
    if m:
        res.update({"wns": float(m.group(1)), "tns": float(m.group(2)), "tns_failing_endpoints": int(m.group(3)),
                    "total_endpoints": int(m.group(4)), "whs": float(m.group(5)), "ths": float(m.group(6)),
                    "ths_failing_endpoints": int(m.group(7))})
    m = re.search(r"All user specified timing constraints are met", t)
    res["constraints_met"] = bool(m)
    return res


def parse_paths(path):
    """First (worst) path of a report_timing file."""
    t = _read(path)
    res = {}
    m = re.search(r"Slack \((MET|VIOLATED)\)\s*:\s*([-\d.]+)ns", t)
    if m:
        res["slack"] = float(m.group(2))
    m = re.search(r"Data Path Delay:\s*([\d.]+)ns\s+\(logic ([\d.]+)ns \(([\d.]+)%\)\s+route ([\d.]+)ns \(([\d.]+)%\)\)", t)
    if m:
        res.update({"data_path_delay": float(m.group(1)), "logic_delay": float(m.group(2)), "logic_pct": float(m.group(3)),
                    "route_delay": float(m.group(4)), "route_pct": float(m.group(5))})
    m = re.search(r"Logic Levels:\s*(\d+)\s*\((.*?)\)", t)
    if m:
        res["logic_levels"] = int(m.group(1))
        res["logic_level_detail"] = m.group(2).strip()
    m = re.search(r"Source:\s*(\S+)", t)
    res["source"] = m.group(1) if m else None
    m = re.search(r"Destination:\s*(\S+)", t)
    res["destination"] = m.group(1) if m else None
    m = re.search(r"Requirement:\s*([\d.]+)ns", t)
    if m:
        res["requirement"] = float(m.group(1))
    return res


def parse_power_text(path):
    t = _read(path)
    res = {}
    for key, pat in (("total_w", r"Total On-Chip Power \(W\)\s*\|\s*([\d.]+)"), ("dynamic_w", r"Dynamic \(W\)\s*\|\s*([\d.]+)"),
                     ("static_w", r"Device Static \(W\)\s*\|\s*([\d.]+)")):
        m = re.search(pat, t)
        res[key] = float(m.group(1)) if m else None
    m = re.search(r"Confidence Level\s*\|\s*(\w+)", t)
    res["confidence"] = m.group(1) if m else None
    m = re.search(r"Simulation Activity File\s*\|\s*(.+?)\s*\|", t)
    res["activity_file"] = "none (vectorless)" if (m and m.group(1).strip() == "---") else ("SAIF" if m else None)
    m = re.search(r"Design Nets Matched\s*\|\s*(NA|\d+%\s*\((\d+)/(\d+)\))", t)
    if m and m.group(2):
        res["nets_matched"] = int(m.group(2))
        res["nets_total"] = int(m.group(3))
        res["nets_matched_pct"] = 100.0 * int(m.group(2)) / int(m.group(3))
    return res


def parse_power_xml(path):
    """Per-rail supply currents (A) -> power at full precision (mW). Dynamic and static
    sum exactly to the total because both are derived from the same rail table."""
    root = ET.parse(path).getroot()
    dyn = stat = tot = 0.0
    rails = {}
    for tbl in root.iter("table"):
        rows = tbl.findall("tablerow")
        hdr = [c.get("contents") for c in rows[0]] if rows else []
        if hdr[:1] == ["Source"] and "Dynamic (A)" in hdr:
            for r in rows[1:]:
                cells = [c.get("contents").strip() for c in r]
                v, ta, da, sa = (float(cells[1]), float(cells[2]), float(cells[3]), float(cells[4]))
                rails[cells[0]] = {"voltage": v, "total_a": ta, "dynamic_a": da, "static_a": sa}
                dyn += v * da * 1000
                stat += v * sa * 1000
                tot += v * ta * 1000
    return {"dynamic_mw": dyn, "static_mw": stat, "total_mw": tot, "rails": rails}


def parse_route_status(path):
    t = _read(path)
    res = {}
    for key, pat in (("routing_errors", r"# of nets with routing errors\.*\s*:\s*(\d+)"),
                     ("fully_routed", r"# of fully routed nets\.*\s*:\s*(\d+)"),
                     ("unrouted", r"# of unrouted nets\.*\s*:\s*(\d+)")):
        m = re.search(pat, t)
        res[key] = int(m.group(1)) if m else None
    return res


def parse_hier(path):
    """Group the hierarchical utilization report the way manuscript Table VIII does:
    control + storage = the top module's own logic, plus one group per arithmetic module type."""
    t = _read(path)
    groups = {"Control + storage": [0, 0, 0, 0, 0, 0], "Multiplier(s)": [0, 0, 0, 0, 0, 0],
              "Adder(s)": [0, 0, 0, 0, 0, 0], "Subtractor(s)": [0, 0, 0, 0, 0, 0]}
    for line in t.splitlines():
        m = re.match(r"\|(\s*)(\S+)\s*\|\s*(\S+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", line)
        if not m:
            continue
        depth = len(m.group(1)) // 2
        name, module = m.group(2), m.group(3)
        total_luts, logic_luts, lutram, ffs, dsp = int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(8)), int(m.group(11))
        if depth == 1 and name.startswith("("):            # the top module's own logic
            groups["Control + storage"][:5] = [total_luts, logic_luts, lutram, ffs, dsp]
        elif depth == 1:
            # Vivado uniquifies repeated modules (mod_add_0, mult_unit_3, ...)
            g = {"mult_unit": "Multiplier(s)", "mod_add": "Adder(s)", "mod_sub": "Subtractor(s)"}.get(
                re.sub(r"_\d+$", "", module))
            if g:
                grp = groups[g]
                grp[0] += total_luts
                grp[1] += logic_luts
                grp[2] += lutram
                grp[3] += ffs
                grp[4] += dsp
                grp[5] += 1
    return {k: {"luts": v[0], "logic_luts": v[1], "lutram": v[2], "ffs": v[3], "dsp": v[4], "instances": v[5]}
            for k, v in groups.items()}


def read_slacks(path):
    with open(path) as fh:
        return [float(x) for x in fh.read().split()]


def read_closure(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            rows.append({"run": r["run"], "period_ns": float(r["period_ns"]), "wns_ns": float(r["wns_ns"]),
                         "closed": r["closed"] == "YES"})
    return rows
