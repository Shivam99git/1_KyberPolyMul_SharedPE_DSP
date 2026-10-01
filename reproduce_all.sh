#!/usr/bin/env bash
# ============================================================================
# reproduce_all.sh -- single entry point for the reproducibility artifact of
# "Resource-shared single-PE NTT polynomial multiplier for CRYSTALS-Kyber".
#
#   ./reproduce_all.sh                 full run if Vivado is found, otherwise --from-reports
#   ./reproduce_all.sh --quick         RTL simulation + software analyses; no Vivado place-and-route,
#                                      no TVLA regeneration (except one determinism check);
#                                      FPGA numbers are parsed from the archived raw reports
#   ./reproduce_all.sh --full          everything: Vivado synthesis/implementation/power, all TVLA runs
#   ./reproduce_all.sh --from-reports  no Vivado/xsim needed: parse the archived reports and archived
#                                      simulator logs, re-analyse the archived raw TVLA data,
#                                      regenerate all tables, figures and the consistency report
#   ./reproduce_all.sh --clean         remove generated outputs only (results/, build/, reports/generated/)
#
# Other options:  --parallel-vivado   run the three Vivado flows concurrently (stages 6-8)
#                 --jobs N            worker processes for the TVLA simulation (default: cores - 1)
#                 -h | --help
#
# Exit status: 0 = no FAIL;  1 = at least one stage or consistency check FAILED.
# SKIPPED (a required proprietary tool is unavailable) never causes a non-zero status.
# Every command's stdout/stderr is kept in results/logs/.
# ============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
PY="${PYTHON:-python3}"
LOG_DIR="$ROOT_DIR/results/logs"
STATUS_TSV="$ROOT_DIR/results/stage_status.tsv"

MODE="auto"; PARALLEL_VIVADO=0; JOBS=""; ARGS_RECORD="$*"
usage() { sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
    case "$1" in
        --quick) MODE="quick" ;;
        --full) MODE="full" ;;
        --from-reports) MODE="from-reports" ;;
        --clean) MODE="clean" ;;
        --parallel-vivado) PARALLEL_VIVADO=1 ;;
        --jobs) shift; JOBS="${1:?--jobs needs a number}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------- --clean
if [ "$MODE" = "clean" ]; then
    echo "Removing generated outputs (raw archives in reports/raw, data/ and rtl/ are kept)..."
    rm -rf "$ROOT_DIR/results" "$ROOT_DIR/build" "$ROOT_DIR/.Xil"
    find "$ROOT_DIR/reports/generated" -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} + 2>/dev/null || true
    find "$ROOT_DIR/manuscript_artifacts" -type f \( -name '*.csv' -o -name '*.tex' -o -name '*.pdf' -o -name '*.png' -o -name INDEX.md \) -delete 2>/dev/null || true
    find "$ROOT_DIR" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
    echo "done."
    exit 0
fi

# ---------------------------------------------------------------- tools
if ! command -v vivado >/dev/null 2>&1 && [ -n "${VIVADO_SETTINGS:-}" ] && [ -f "$VIVADO_SETTINGS" ]; then
    # shellcheck disable=SC1090
    source "$VIVADO_SETTINGS" >/dev/null 2>&1 || true
fi
HAVE_VIVADO=0
if command -v vivado >/dev/null 2>&1 && command -v xvlog >/dev/null 2>&1 && command -v xsim >/dev/null 2>&1; then HAVE_VIVADO=1; fi
if [ "$MODE" = "auto" ]; then
    if [ "$HAVE_VIVADO" = 1 ]; then MODE="full"; else
        MODE="from-reports"
        echo "NOTE: Vivado (vivado/xvlog/xsim) not found in PATH -> running in --from-reports mode."
        echo "      Set VIVADO_SETTINGS=/path/to/Vivado/2024.2/settings64.sh or source it to enable --quick/--full."
    fi
fi
if [ "$HAVE_VIVADO" = 0 ] && { [ "$MODE" = "full" ] || [ "$MODE" = "quick" ]; }; then
    echo "NOTE: Vivado not found: RTL simulation and Vivado flows will be reported SKIPPED."
fi

mkdir -p "$LOG_DIR" "$ROOT_DIR/results"/{csv,json,tables,figures,sim} "$ROOT_DIR/build" "$ROOT_DIR/reports/generated/vivado"
: > "$STATUS_TSV"
TVLA_JOBS=""; [ -n "$JOBS" ] && TVLA_JOBS="--jobs $JOBS"
T_ALL=$SECONDS
FAILED_STAGES=0

# ---------------------------------------------------------------- stage helpers
begin_stage() {  # number title evidence
    STAGE_N="$1"; STAGE_TITLE="$2"; STAGE_EVID="$3"; STAGE_NOTE=""
    STAGE_PASS=0; STAGE_FAIL=0; STAGE_SKIP=0; STAGE_T0=$SECONDS
    STAGE_LOG="$LOG_DIR/stage_$(printf '%02d' "$1").log"
    : > "$STAGE_LOG"
    echo
    echo "[$1/12] $2"
}
run_step() {  # description command...
    local desc="$1"; shift
    { echo "--- $desc"; echo "\$ $*"; } >> "$STAGE_LOG"
    set +e
    "$@" 2>&1 | tee -a "$STAGE_LOG" | sed 's/^/    /'
    local rc=${PIPESTATUS[0]}
    set -e
    case "$rc" in
        0) STAGE_PASS=$((STAGE_PASS + 1)) ;;
        3) STAGE_SKIP=$((STAGE_SKIP + 1)); echo "    [SKIPPED] $desc" ;;
        *) STAGE_FAIL=$((STAGE_FAIL + 1)); echo "    [FAIL] $desc (exit status $rc; full output: results/logs/$(basename "$STAGE_LOG"))" ;;
    esac
    return 0
}
skip_step() {  # reason
    STAGE_SKIP=$((STAGE_SKIP + 1)); STAGE_NOTE="$1"
    echo "    [SKIPPED] $1"
    echo "--- SKIPPED: $1" >> "$STAGE_LOG"
}
end_stage() {
    local status="PASS"
    if [ "$STAGE_FAIL" -gt 0 ]; then status="FAIL"; FAILED_STAGES=$((FAILED_STAGES + 1));
    elif [ "$STAGE_PASS" -eq 0 ] && [ "$STAGE_SKIP" -gt 0 ]; then status="SKIPPED"; fi
    local secs=$((SECONDS - STAGE_T0))
    if [ -n "$STAGE_NOTE" ]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$STAGE_N" "$STAGE_TITLE" "$status" "$secs" "$STAGE_EVID" "$STAGE_NOTE" >> "$STATUS_TSV"
    else
        printf '%s\t%s\t%s\t%s\t%s\n' "$STAGE_N" "$STAGE_TITLE" "$status" "$secs" "$STAGE_EVID" >> "$STATUS_TSV"
    fi
    echo "[$STAGE_N/12] $STAGE_TITLE: $status (${secs}s)"
}

SIM_FROM_LOGS=""   # set in from-reports mode
sim() {  # experiments...
    if [ -n "$SIM_FROM_LOGS" ]; then
        run_step "RTL simulation results ($1) from archived logs" "$PY" scripts/verification/run_rtl_sim.py --from-logs reports/raw/sim --only "$1"
    elif [ "$HAVE_VIVADO" = 1 ]; then
        run_step "RTL simulation ($1)" "$PY" scripts/verification/run_rtl_sim.py --only "$1"
    else
        skip_step "RTL simulation ($1): required tool unavailable (xvlog/xsim not in PATH); use --from-reports or install Vivado 2024.2"
    fi
}

SIM_EVID="regenerated (xsim)"
[ "$MODE" = "from-reports" ] && { SIM_FROM_LOGS=1; SIM_EVID="archived logs (reports/raw/sim)"; }
[ "$HAVE_VIVADO" = 0 ] && [ "$MODE" != "from-reports" ] && SIM_EVID="not run"

echo "Mode: $MODE   (Vivado found: $([ "$HAVE_VIVADO" = 1 ] && echo yes || echo no))   repository: $(basename "$ROOT_DIR")"

# ================================================================ [1/12]
begin_stage 1 "Environment check" "local"
run_step "environment" "$PY" scripts/reporting/check_environment.py
end_stage

# ================================================================ [2/12]
begin_stage 2 "Functional/reference-model verification" "regenerated (python)"
run_step "test vectors reproduce byte-for-byte from their seeds" "$PY" scripts/verification/gen_test_vectors.py
run_step "software reference model (NTT vs independent schoolbook)" "$PY" scripts/verification/run_reference_tests.py
end_stage

# ================================================================ [3/12]
begin_stage 3 "Barrett exhaustive verification" "$SIM_EVID + python"
sim barrett
run_step "Barrett reduction over all 2^24 inputs" "$PY" scripts/verification/barrett_exhaustive.py
end_stage

# ================================================================ [4/12]
begin_stage 4 "RTL simulation and cycle-count verification" "$SIM_EVID"
sim functional_shared,functional_baseline,functional_pipelined
sim shuffled
sim masking
run_step "RTL output vs independent schoolbook reference" "$PY" scripts/verification/run_reference_tests.py
run_step "analytical cycle model vs RTL" "$PY" scripts/verification/cycle_model.py
end_stage

# ================================================================ [5/12]
begin_stage 5 "Constant-time/control-trace verification" "$SIM_EVID"
sim constant_time_shared,constant_time_pipelined,constant_time_baseline
run_step "control / address trajectory report" "$PY" scripts/verification/ct_report.py
end_stage

# ================================================================ [6-8/12] Vivado flows
VIV_FRESH=0
vivado_flow() {  # design script
    local design="$1" script="$2"
    mkdir -p "build/vivado/$design"
    ( cd "build/vivado/$design" && vivado -mode batch -nojournal -log "$LOG_DIR/vivado_$design.log" \
        -source "$ROOT_DIR/scripts/synthesis/$script" )
}
vivado_stage() {  # number title design script
    begin_stage "$1" "$2" "$([ "$MODE" = full ] && echo 'regenerated (Vivado)' || echo 'archived reports (reports/raw/vivado)')"
    if [ "$MODE" != "full" ]; then
        skip_step "Vivado synthesis/implementation: not run in --$MODE mode; archived reports under reports/raw/vivado are parsed instead"
    elif [ "$HAVE_VIVADO" = 0 ]; then
        skip_step "Vivado synthesis/implementation: vivado not found in PATH (see docs/reproducibility.md to regenerate)"
    elif [ "$PARALLEL_VIVADO" = 1 ] && [ "$1" -ne 6 ]; then
        echo "    (ran concurrently with stage 6; see results/logs/vivado_$3.log)"; STAGE_PASS=$((STAGE_PASS + 1))
    else
        if [ "$PARALLEL_VIVADO" = 1 ]; then
            run_step "Vivado flows (shared-PE, per-phase, pipelined) in parallel" bash -c '
                set -e; cd "'"$ROOT_DIR"'"
                mkdir -p build/vivado/shared_pe build/vivado/per_phase_baseline build/vivado/pipelined_barrett
                for d in shared_pe:run_shared_pe.tcl per_phase_baseline:run_baseline.tcl pipelined_barrett:run_pipelined.tcl; do
                    n=${d%%:*}; s=${d##*:}
                    ( cd build/vivado/$n && vivado -mode batch -nojournal -log "'"$LOG_DIR"'/vivado_$n.log" -source "'"$ROOT_DIR"'/scripts/synthesis/$s" ) > "'"$LOG_DIR"'/vivado_$n.stdout" 2>&1 &
                done
                rc=0; for p in $(jobs -p); do wait $p || rc=1; done; exit $rc'
        else
            run_step "vivado -mode batch -source scripts/synthesis/$4" vivado_flow "$3" "$4"
        fi
        [ "$STAGE_FAIL" -eq 0 ] && { test -s "reports/generated/vivado/$3/closure_summary.csv" && VIV_FRESH=$((VIV_FRESH + 1)) \
            || { echo "    [FAIL] no closure_summary.csv produced for $3"; STAGE_FAIL=$((STAGE_FAIL + 1)); }; }
    fi
    end_stage
}
if [ "$HAVE_VIVADO" = 1 ] && [ "$MODE" = "full" ]; then
    rm -rf reports/generated/vivado/*   # a full run must not mix with leftovers of an earlier one
fi
vivado_stage 6 "Shared-PE synthesis/implementation" shared_pe run_shared_pe.tcl
vivado_stage 7 "Per-phase baseline synthesis/implementation" per_phase_baseline run_baseline.tcl
vivado_stage 8 "Pipelined-Barrett implementation" pipelined_barrett run_pipelined.tcl

# ================================================================ [9/12]
if [ "$MODE" = "full" ] && [ "$HAVE_VIVADO" = 1 ] && { [ "$VIV_FRESH" -ge 3 ] || [ "$PARALLEL_VIVADO" = 1 ]; }; then
    VIV_DIR="reports/generated/vivado"; VIV_EVID="regenerated (Vivado)"
else
    VIV_DIR="reports/raw/vivado"; VIV_EVID="archived reports (reports/raw/vivado)"
fi
begin_stage 9 "Resource/timing/power extraction" "$VIV_EVID"
if [ "$MODE" = "full" ] && [ "$HAVE_VIVADO" = 1 ] && [ "$VIV_DIR" = "reports/generated/vivado" ]; then
    run_step "SAIF-annotated power at the common period" "$PY" scripts/power/run_power.py
fi
run_step "parse Vivado reports ($VIV_DIR)" "$PY" scripts/reporting/extract_results.py --reports-dir "$VIV_DIR"
run_step "derived metrics (latency, percentages, figures of merit)" "$PY" scripts/reporting/derive_metrics.py
if [ "$VIV_DIR" = "reports/generated/vivado" ]; then
    run_step "regenerated reports vs archived reports" "$PY" scripts/reporting/compare_reports.py
fi
end_stage

# ================================================================ [10/12]
TV_EVID="archived raw data (data/tvla) re-analysed"
[ "$MODE" = "full" ] && TV_EVID="regenerated (python)"
begin_stage 10 "TVLA/masking/shuffling experiments" "$TV_EVID"
sim trace_shared,trace_baseline
run_step "power model vs RTL register traces" "$PY" scripts/tvla/validate_model_vs_rtl.py
rm -rf results/tvla_raw
case "$MODE" in
    full)
        run_step "TVLA raw data (all experiments, seeded)" "$PY" scripts/tvla/run_tvla.py $TVLA_JOBS --out-dir results/tvla_raw
        run_step "regenerated raw TVLA data vs archived" "$PY" scripts/tvla/compare_archived.py
        run_step "Welch t analysis" "$PY" scripts/tvla/analyze_tvla.py --moments-dir results/tvla_raw ;;
    quick)
        run_step "TVLA determinism check (shared-PE experiment regenerated, 4 x 400 traces)" bash -c \
            "\"$PY\" scripts/tvla/run_tvla.py $TVLA_JOBS --experiments main_shared --out-dir results/tvla_raw && \"$PY\" scripts/tvla/compare_archived.py"
        run_step "Welch t analysis of the archived raw TVLA data" "$PY" scripts/tvla/analyze_tvla.py --moments-dir data/tvla ;;
    *)
        run_step "Welch t analysis of the archived raw TVLA data" "$PY" scripts/tvla/analyze_tvla.py --moments-dir data/tvla ;;
esac
run_step "additive masking checks" "$PY" scripts/masking/run_masking_check.py
run_step "shuffled-issue-order checks" "$PY" scripts/shuffling/run_shuffling_check.py
end_stage

# ================================================================ [11/12]
begin_stage 11 "Tables and figures" "regenerated from results/"
run_step "tables (CSV + LaTeX)" "$PY" scripts/reporting/format_tables.py
run_step "figures (PDF + PNG)" "$PY" scripts/figures/make_figures.py
run_step "manuscript_artifacts/" "$PY" scripts/reporting/collect_manuscript_artifacts.py
end_stage

# ================================================================ [12/12]
begin_stage 12 "Manuscript-result consistency report" "results/"
run_step "generated vs expected manuscript values (all checks: results/logs/manuscript_consistency.txt)" "$PY" scripts/reporting/check_manuscript_results.py --only-problems
end_stage
"$PY" scripts/reporting/write_metadata.py --mode="$MODE" "--args=$ARGS_RECORD" >/dev/null
"$PY" scripts/reporting/make_report.py >/dev/null

# ---------------------------------------------------------------- summary
echo
echo "================================ SUMMARY ($MODE, $((SECONDS - T_ALL))s) ================================"
awk -F'\t' '{ printf "  [%2s/12] %-52s %s\n", $1, $2, $3 }' "$STATUS_TSV"
"$PY" - <<'PYEOF'
import json, os
j = lambda n: json.load(open(os.path.join("results", "json", n))) if os.path.exists(os.path.join("results", "json", n)) else None
c = j("manuscript_consistency.json")
if c:
    k = c["counts"]
    print(f"  manuscript consistency: {k['PASS']} PASS, {k['WARN']} WARN, {k['FAIL']} FAIL, {k['SKIPPED']} SKIPPED")
    for x in c["checks"]:
        if x["status"] in ("FAIL", "WARN"):
            print(f"    {x['status']:5s} {x['id']}: expected {x['expected']}, generated {x['generated']}")
cs, dm = j("cycle_summary.json"), j("derived_metrics.json")
if cs:
    print("  cycles: primary %s, pipelined %s, per-phase %s" % tuple(f"{cs[d]['rtl_total']:,}" if cs[d]['rtl_total'] else "SKIPPED"
          for d in ("shared_pe", "pipelined_barrett", "per_phase_baseline")))
if dm and "shared_pe" in dm["designs"]:
    m = dm["designs"]["shared_pe"]
    print(f"  shared-PE: {m['luts']} LUT, {m['ffs']} FF, {m['dsp']} DSP48E1, {m['bram36']} BRAM, Fmax {m.get('fmax_closed_mhz', float('nan')):.1f} MHz")
PYEOF
echo "  report: results/REPRODUCIBILITY_REPORT.md"
echo "  logs  : results/logs/"
CONS_FAIL=$("$PY" -c "import json;print(json.load(open('results/json/manuscript_consistency.json'))['counts']['FAIL'])" 2>/dev/null || echo 0)
if [ "$FAILED_STAGES" -gt 0 ] || [ "$CONS_FAIL" -gt 0 ]; then
    echo "RESULT: FAIL ($FAILED_STAGES stage(s) failed, $CONS_FAIL consistency check(s) failed)"
    exit 1
fi
echo "RESULT: no FAIL"
