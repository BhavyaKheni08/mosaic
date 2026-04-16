#!/usr/bin/env bash
# =============================================================================
# run_all_evals.sh — MOSAIC Phase 7 Master Evaluation Runner
# =============================================================================
# Executes all benchmark scripts in sequence and aggregates exit codes.
#
# Usage:
#   chmod +x benchmarks/run_all_evals.sh
#   ./benchmarks/run_all_evals.sh [--dry-run] [--save] [--samples N]
#
# Flags:
#   --dry-run   Skip live API / Neo4j calls (safe for CI pipelines)
#   --save      Persist JSON results under benchmarks/results/
#   --samples N How many QA samples to evaluate (default: 100)
#
# Exit codes:
#   0  All evaluations completed without fatal errors
#   1  One or more evaluations failed
# =============================================================================

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$SCRIPT_DIR/results"
DRY_RUN=false
SAVE_FLAG=""
SAMPLES=100
MOSAIC_ENDPOINT="http://localhost:8000"
PYTHON="${PYTHON:-python3}"

# ── Colour helpers ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log_info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${RESET} $*"; }
log_section() { echo -e "\n${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; \
                echo -e "${BOLD}  $*${RESET}"; \
                echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; }

# ── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)   DRY_RUN=true; shift ;;
    --save)      SAVE_FLAG="--save"; shift ;;
    --samples)   SAMPLES="$2"; shift 2 ;;
    --endpoint)  MOSAIC_ENDPOINT="$2"; shift 2 ;;
    *) log_error "Unknown argument: $1"; exit 1 ;;
  esac
done

FAIL_COUNT=0
PASS_COUNT=0
START_TIME=$(date +%s)

mkdir -p "$RESULTS_DIR"

# ── Preflight ────────────────────────────────────────────────────────────────
log_section "MOSAIC Phase 7 — Evaluation Suite"
log_info "Project root : $PROJECT_ROOT"
log_info "Results dir  : $RESULTS_DIR"
log_info "Python       : $($PYTHON --version 2>&1)"
log_info "Samples      : $SAMPLES"
log_info "Dry run      : $DRY_RUN"
log_info "Save results : ${SAVE_FLAG:-no}"
log_info "MOSAIC API   : $MOSAIC_ENDPOINT"

# Check Python
if ! command -v "$PYTHON" &>/dev/null; then
  log_error "Python interpreter not found. Set PYTHON env variable."
  exit 1
fi

# ── Helper: run one evaluation ────────────────────────────────────────────────
run_eval() {
  local label="$1"
  local script="$2"
  shift 2
  local extra_args=("$@")

  log_section "$label"
  log_info "Running: $PYTHON $script ${extra_args[*]}"

  if $PYTHON "$SCRIPT_DIR/$script" "${extra_args[@]}"; then
    log_ok "$label completed successfully."
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    log_error "$label FAILED (exit code $?)."
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

# ── 1. Accuracy Evaluation — TriviaQA ────────────────────────────────────────
run_eval \
  "1/4 Accuracy Eval (TriviaQA)" \
  "accuracy_eval.py" \
  --dataset triviaqa \
  --samples "$SAMPLES" \
  --mosaic-endpoint "$MOSAIC_ENDPOINT" \
  $SAVE_FLAG

# ── 2. Accuracy Evaluation — PopQA ───────────────────────────────────────────
run_eval \
  "2/4 Accuracy Eval (PopQA)" \
  "accuracy_eval.py" \
  --dataset popqa \
  --samples "$((SAMPLES / 2))" \
  --mosaic-endpoint "$MOSAIC_ENDPOINT" \
  $SAVE_FLAG

# ── 3. Contradiction Detection ────────────────────────────────────────────────
run_eval \
  "3/4 Contradiction Detection" \
  "contradiction_tester.py" \
  --use-synthetic \
  --mosaic-endpoint "$MOSAIC_ENDPOINT" \
  $SAVE_FLAG

# ── 4. Staleness / Time-to-Correction Audit ───────────────────────────────────
STALENESS_ARGS=(
  --seeds 20
  --poll-interval 3
  --timeout 60
  --mosaic-endpoint "$MOSAIC_ENDPOINT"
  $SAVE_FLAG
)
if $DRY_RUN; then
  STALENESS_ARGS+=(--dry-run)
fi
run_eval \
  "4/4 Staleness Audit" \
  "staleness_audit.py" \
  "${STALENESS_ARGS[@]}"

# ── 5. Cost Analysis (depends on accuracy eval output) ────────────────────────
log_section "5/5 API Cost vs. Quality Analysis"
LATEST_ACC=$(ls -t "$RESULTS_DIR"/accuracy_triviaqa_*_raw.json 2>/dev/null | head -1 || true)

COST_ARGS=(--samples "$SAMPLES" --model gemini-1.5-pro $SAVE_FLAG)
if [[ -n "${LATEST_ACC:-}" ]]; then
  log_info "Using accuracy output: $LATEST_ACC"
  COST_ARGS=(--input "$LATEST_ACC" $SAVE_FLAG)
else
  log_warn "No accuracy output found; using synthetic data for cost analysis."
fi

if $PYTHON "$SCRIPT_DIR/cost_analysis.py" "${COST_ARGS[@]}"; then
  log_ok "Cost analysis completed."
  PASS_COUNT=$((PASS_COUNT + 1))
else
  log_error "Cost analysis FAILED."
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ── Summary ───────────────────────────────────────────────────────────────────
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

log_section "Evaluation Suite Summary"
echo -e "  ${GREEN}Passed${RESET} : $PASS_COUNT"
echo -e "  ${RED}Failed${RESET} : $FAIL_COUNT"
echo -e "  Elapsed  : ${ELAPSED}s"
echo -e "  Results  : $RESULTS_DIR"
echo ""

if [[ $FAIL_COUNT -gt 0 ]]; then
  log_error "$FAIL_COUNT evaluation(s) failed. Check logs above."
  exit 1
fi

log_ok "All evaluations completed successfully. 🎉"
exit 0
