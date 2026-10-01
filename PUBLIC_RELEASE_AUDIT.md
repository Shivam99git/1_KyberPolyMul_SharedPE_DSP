# Public Release Audit

Audit date: 2026-10-01 (local reproducibility checks)

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

- `./reproduce_all.sh --from-reports`: PASS, completed in 178 seconds; 200 consistency checks
  passed, four warned, none failed. Functional results: 256 multiplications and 65,536 output
  coefficients per design, zero mismatches. Barrett: all 16,777,216 24-bit inputs, zero
  mismatches. Cycle counts: 27,269 (shared and baseline), 30,853 (pipelined). Archived FPGA
  evidence parsed successfully. Vivado reruns were skipped because Vivado is unavailable.
- `./reproduce_all.sh --quick`: PASS, completed in 331 seconds; 200 consistency checks passed,
  four warned, none failed. Deterministically regenerated TVLA moments matched the archived
  shared-PE moments bit-for-bit. xsim and fresh Vivado stages were skipped because those tools
  are unavailable; archived simulation evidence was checked.
- `./reproduce_all.sh --full`: NOT RUN; Vivado/xsim are not installed in this environment.
- README quick and report-only entry-point commands were executed. The full-mode command and
  individual Vivado flows could not be run because the required tool is absent. Direct setup
  commands containing placeholder clone/install paths are reviewer instructions, not local tests.

## Numerical discrepancies and limitations

Four TVLA consistency warnings remain. The expected manuscript range for five “independent fixed
secrets” is max |t| 82.1–87.2 and 24.3–26.7% of cycles above threshold; the corrected experiment
using five random fixed-secret polynomials generated max |t| 49.795–69.345 and 21.780–22.342%.
The originally run constant-coefficient secret experiment reproduces the expected range. Both
measurements and the source explanation are retained; neither expected nor generated values were
substituted. See `docs/security_evaluation.md` and `results/REPRODUCIBILITY_REPORT.md`.

Full synthesis, place-and-route, power regeneration, and fresh RTL simulation require licensed
Vivado 2024.2 and remain to be run in that environment. TVLA results are simulated register-level
proxies; they do not establish physical side-channel immunity. The repository has no configured
local review workflow for Vivado reruns; perform those before making claims based on newly generated
FPGA implementation data.
