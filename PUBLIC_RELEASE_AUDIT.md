# Public Release Audit

Audit date: 2026-10-01 (Vivado 2024.2 full reproduction)

## Repository contents and scope

The public release is organized at repository root. It contains the shared-PE, per-phase baseline,
and pipelined-Barrett RTL; simulation testbenches; Python/Tcl reproduction scripts; FPGA
constraints; deterministic vectors; raw TVLA moments; scrubbed archived simulator and Vivado
reports; expected manuscript comparison values; generated tables/figures; and architecture,
verification, security, baseline, reproducibility, and result-mapping documentation.

Local working material is excluded by `.gitignore`: manuscript working copies (`Paper/`), dated
review/audit folders, old flat source copies, and the prior packaging workspace. Vivado caches,
intermediate simulation outputs, and local result logs are also excluded. These files have not been
deleted from the working directory.

The optional GitHub Actions workflow is not included in the published tree: the authenticated
GitHub token does not have the `workflow` scope required to push workflow files. The local
reproduction script remains the validated entry point.

Published as a public repository at
`https://github.com/Shivam99git/1_KyberPolyMul_SharedPE_DSP` on branch `main`. The initial
commit author and committer use the project owner's GitHub noreply identity. After the push,
GitHub's contributors endpoint listed only `Shivam99git`.

## Reproduction commands and dependencies

Single entry point: `./reproduce_all.sh`, with `--quick`, `--full`, `--from-reports`, and `--clean`.
Optional controls include `--parallel-vivado` and `--jobs N`. Dependencies are Python 3, the packages
in `requirements.txt`, Bash, and—only for fresh RTL simulation and FPGA implementation—Xilinx
Vivado 2024.2 with `xvlog`, `xelab`, and `xsim` available.

## Evidence inventory

- RTL: organized modules under `rtl/common/`, `rtl/shared_pe/`, `rtl/per_phase_baseline/`, and
  `rtl/pipelined_barrett/`.
- Testbenches: functional, Barrett, constant-time, and power/trace testbenches under `tb/`.
- Archived raw evidence: 217 files under `reports/raw/` (Vivado reports plus simulator logs,
  register traces, and RTL output vectors); nine compressed TVLA moment files under `data/tvla/`.
- Generated evidence: `results/REPRODUCIBILITY_REPORT.md`, machine-readable CSV/JSON, figures,
  and 26 manuscript artifacts under `manuscript_artifacts/`.
- Manuscript claim map: `docs/manuscript_result_mapping.md`; expected values remain separated in
  `data/expected/manuscript_results.json`.
- Experiment seeds are recorded in scripts and `results/reproduction_metadata.json`.

## Public-material screening

The release-candidate text/source scan found no private home-directory paths, private-key blocks,
AWS access-key patterns, or GitHub personal-token patterns. The release does not include the
manuscript working directories, local Vivado caches, build directories, or credentials. Included
RTL is project RTL; this audit found no separately licensed third-party RTL source. Archived
reports describe tool output and remain identified as Vivado 2024.2 evidence. MIT license and
citation metadata are at the repository root; verify ownership and coauthor/license approval
before publishing if project policy requires it.

## Validation performed

- `./reproduce_all.sh --from-reports`: PASS in 178 seconds; 200 checks passed, four warned, none
  failed. Functional results: 256 products and 65,536 output coefficients per design, zero
  mismatches. Barrett: all 16,777,216 24-bit inputs, zero mismatches. Cycle counts: 27,269 (shared
  and baseline), 30,853 (pipelined).
- `./reproduce_all.sh --quick`: PASS in 331 seconds; 200 checks passed, four warned, none failed.
  Regenerated shared-PE TVLA moments matched the archived file bit-for-bit.
- `VIVADO_SETTINGS=<Vivado-install>/2024.2/settings64.sh ./reproduce_all.sh --full`: PASS in
  1,572 seconds (26m12s) with Vivado/xsim 2024.2. All 12 stages passed. All 16 fresh Vivado report
  runs parsed identically to archived evidence; nine regenerated TVLA moment files were
  bit-identical to archives. Full-run consistency: 200 PASS, 4 WARN, 0 FAIL, 0 SKIPPED.
- Fresh full-mode functional, Barrett, cycle-count, constant-time, masking, and shuffling RTL
  simulations passed. Each functional core checked 256 products / 65,536 coefficients with zero
  mismatches; RTL Barrett reducers checked all 2^24 inputs with zero mismatches.
- Fresh Vivado used `xc7a35tcpg236-1` and release 2024.2. The three flows closed at 13.418 ns,
  13.798 ns, and 8.300 ns. Resource, timing, and power checks passed.

## Numerical discrepancies and limitations

Four TVLA checks in manuscript Sec. V-B warn. Expected → generated (difference): min max |t|,
82.1 → 49.795347 (−32.304653); max max |t|, 87.2 → 69.345302 (−17.854698); minimum percentage
above threshold, 24.3% → 21.779927% (−2.520073 percentage points); maximum, 26.7% → 22.342097%
(−4.357903 percentage points). The manuscript says “five independent fixed secrets.” The
corrected experiment creates five random fixed-secret polynomials and produces the generated
range. The original experiment code recreated the same PRNG for each coefficient, yielding five
constant-coefficient polynomials in `scripts/tvla/run_tvla.py`; that version reproduces the
manuscript range (max |t| 82.048–87.230; 24.297–26.682%). Evidence is the expected-value checker
row (`results/csv/manuscript_consistency.csv`),
the two datasets in `results/json/tvla_summary.json`, and the analysis in
`docs/security_evaluation.md`. The RTL and manuscript expectations were left unchanged.

Vivado emitted out-of-context port partial-route and register set/reset-priority warnings; the
flows completed without errors or critical warnings, and parsed metrics matched archived reports.
TVLA results are simulated register-level proxies; they do not establish physical side-channel
immunity. The manuscript source used for claim review remains a local working copy and is excluded
from the public repository.
