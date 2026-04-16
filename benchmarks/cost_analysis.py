"""
cost_analysis.py
================
MOSAIC Phase 7 — Benchmark Suite: API Cost vs. Quality Analysis

Calculates token-level API consumption (estimated USD cost) for each query
run through MOSAIC, and correlates it with the quality score returned by the
evaluation harness.  Produces a Pareto-style cost / quality scatter plot.

Usage:
    python cost_analysis.py --samples 50 --save
    python cost_analysis.py --input results/accuracy_triviaqa_raw.json --save

Error convention:
    [MOSAIC-ERR][Component: CostAnalysis][Func: <name>] -> <message>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mosaic.benchmarks.cost")

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Pricing Definitions  (USD per 1 000 tokens, as of 2024-Q4 estimates)
# ---------------------------------------------------------------------------

PRICING: Dict[str, Dict[str, float]] = {
    "gemini-1.5-pro":    {"input": 0.00125, "output": 0.005},
    "gemini-1.5-flash":  {"input": 0.000075, "output": 0.0003},
    "gpt-4o":            {"input": 0.005,   "output": 0.015},
    "gpt-4o-mini":       {"input": 0.00015, "output": 0.0006},
    "llama-3-8b-local":  {"input": 0.0,     "output": 0.0},   # self-hosted
    "default":           {"input": 0.001,   "output": 0.003},
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class QueryRecord:
    """Token usage and quality data for a single query."""
    query_id: str
    question: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    quality_score: float           # EM / F1 / 0-to-1 scale
    latency_ms: float
    pipeline: str = "mosaic"       # "mosaic" | "single_agent"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CostQualityReport:
    """Aggregated cost / quality statistics."""
    total_queries: int
    total_cost_usd: float
    avg_cost_per_query_usd: float
    avg_quality_score: float
    avg_tokens_per_query: int
    cost_per_unit_quality: float    # USD / quality point
    mosaic_avg_cost: float
    single_agent_avg_cost: float
    mosaic_avg_quality: float
    single_agent_avg_quality: float


# ---------------------------------------------------------------------------
# Token Estimator
# ---------------------------------------------------------------------------

class TokenEstimator:
    """Estimates token counts from raw text using a character-based heuristic.

    Replace with `tiktoken` or model-specific tokenizer for production.
    """

    COMPONENT = "TokenEstimator"
    # GPT-family ~: 1 token ≈ 4 chars
    CHARS_PER_TOKEN: float = 4.0

    def estimate(self, prompt: str, completion: str) -> Tuple[int, int]:
        try:
            p_tok = max(1, int(len(prompt) / self.CHARS_PER_TOKEN))
            c_tok = max(1, int(len(completion) / self.CHARS_PER_TOKEN))
            return p_tok, c_tok
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: estimate] -> "
                f"Token estimation failed; prompt_len={len(prompt)}, "
                f"completion_len={len(completion)}. Error: {exc}"
            )
            return 100, 50

    def cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        try:
            rate = PRICING.get(model, PRICING["default"])
            return (
                (prompt_tokens / 1000) * rate["input"]
                + (completion_tokens / 1000) * rate["output"]
            )
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: cost] -> "
                f"Cost calculation failed for model={model}. Error: {exc}"
            )
            return 0.0


# ---------------------------------------------------------------------------
# Synthetic Query Generator (for standalone runs without accuracy_eval output)
# ---------------------------------------------------------------------------

SYNTHETIC_QUERIES = [
    "What is the boiling point of water?",
    "Who wrote Hamlet?",
    "What is the capital of France?",
    "When did World War II end?",
    "How many chromosomes do humans have?",
    "Who developed the theory of general relativity?",
    "What element has atomic number 79?",
    "What is the largest planet in the solar system?",
    "How far is the Moon from Earth on average?",
    "What is the Pythagorean theorem?",
]

SYNTHETIC_ANSWERS = {
    "mosaic":       ["100°C", "William Shakespeare", "Paris", "1945", "46",
                     "Albert Einstein", "Gold", "Jupiter", "384,400 km",
                     "a²+b²=c²"],
    "single_agent": ["100°C", "Shakespeare", "Paris", "1944", "46",
                     "Einstein", "Gold", "Jupiter", "385,000 km",
                     "a squared plus b squared"],
}

GOLD_ANSWERS = ["100°C", "William Shakespeare", "Paris", "1945", "46",
                "Albert Einstein", "Gold", "Jupiter", "384,400 km", "a²+b²=c²"]


def _quality(prediction: str, gold: str) -> float:
    """Simple token-overlap F1 as quality proxy."""
    import re
    pred = set(re.sub(r"[^\w\s]", "", prediction.lower()).split())
    g    = set(re.sub(r"[^\w\s]", "", gold.lower()).split())
    if not pred or not g:
        return 0.0
    common = pred & g
    if not common:
        return 0.0
    p = len(common) / len(pred)
    r = len(common) / len(g)
    return 2 * p * r / (p + r)


# ---------------------------------------------------------------------------
# Record Builder
# ---------------------------------------------------------------------------

class CostAnalyzer:
    COMPONENT = "CostAnalyzer"

    def __init__(self, estimator: TokenEstimator,
                 model: str = "gemini-1.5-pro") -> None:
        self.estimator = estimator
        self.model = model

    def build_from_synthetic(self, n: int = 50) -> List[QueryRecord]:
        """Generate synthetic QueryRecord objects for offline testing."""
        records: List[QueryRecord] = []
        try:
            queries = [SYNTHETIC_QUERIES[i % len(SYNTHETIC_QUERIES)] for i in range(n)]
            for idx, q in enumerate(queries):
                pipeline = "mosaic" if idx % 2 == 0 else "single_agent"
                ans_list = SYNTHETIC_ANSWERS[pipeline]
                ans = ans_list[idx % len(ans_list)]
                gold = GOLD_ANSWERS[idx % len(GOLD_ANSWERS)]

                prompt = f"System prompt context...\n\nQuestion: {q}\nRetrieved context: [passage {idx}]"
                p_tok, c_tok = self.estimator.estimate(prompt, ans)
                cost = self.estimator.cost(self.model, p_tok, c_tok)
                quality = _quality(ans, gold)

                records.append(QueryRecord(
                    query_id=f"q{idx:04d}",
                    question=q,
                    model=self.model,
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    total_tokens=p_tok + c_tok,
                    estimated_cost_usd=round(cost, 8),
                    quality_score=round(quality, 4),
                    latency_ms=round(50 + (idx % 10) * 12.5, 1),
                    pipeline=pipeline,
                ))
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: build_from_synthetic] -> "
                f"Synthetic record build failed at n={n}. Error: {exc}"
            )
        return records

    def build_from_file(self, path: Path) -> List[QueryRecord]:
        """Build QueryRecord objects from accuracy_eval raw JSON output."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            records: List[QueryRecord] = []
            for r in raw:
                for pipeline, ans_key in [
                    ("mosaic", "mosaic_answer"),
                    ("single_agent", "single_agent_answer"),
                ]:
                    if r.get(ans_key) is None:
                        continue
                    ans = r[ans_key]
                    gold = r["gold_answers"][0] if r.get("gold_answers") else ""
                    prompt = f"Question: {r['question']}\nContext: [retrieved docs]"
                    p_tok, c_tok = self.estimator.estimate(prompt, ans)
                    cost = self.estimator.cost(self.model, p_tok, c_tok)
                    records.append(QueryRecord(
                        query_id=r["qa_id"],
                        question=r["question"],
                        model=self.model,
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        total_tokens=p_tok + c_tok,
                        estimated_cost_usd=round(cost, 8),
                        quality_score=round(_quality(ans, gold), 4),
                        latency_ms=r.get("mosaic_latency_ms" if pipeline == "mosaic"
                                         else "single_agent_latency_ms", 0.0),
                        pipeline=pipeline,
                    ))
            logger.info(f"[CostAnalyzer.build_from_file] Loaded {len(records)} records.")
            return records
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: build_from_file] -> "
                f"File load failed for '{path}'. Error: {exc}"
            )
            raise

    def aggregate(self, records: List[QueryRecord]) -> CostQualityReport:
        try:
            n = len(records)
            if n == 0:
                raise ValueError("No records to aggregate.")

            mosaic = [r for r in records if r.pipeline == "mosaic"]
            single = [r for r in records if r.pipeline == "single_agent"]

            total_cost = sum(r.estimated_cost_usd for r in records)
            avg_cost   = total_cost / n
            avg_qual   = sum(r.quality_score for r in records) / n
            avg_tok    = int(sum(r.total_tokens for r in records) / n)
            cpuq       = avg_cost / avg_qual if avg_qual > 0 else float("inf")

            def safe_avg(lst, attr):
                return round(sum(getattr(x, attr) for x in lst) / len(lst), 6) if lst else 0.0

            return CostQualityReport(
                total_queries=n,
                total_cost_usd=round(total_cost, 6),
                avg_cost_per_query_usd=round(avg_cost, 8),
                avg_quality_score=round(avg_qual, 4),
                avg_tokens_per_query=avg_tok,
                cost_per_unit_quality=round(cpuq, 8),
                mosaic_avg_cost=safe_avg(mosaic, "estimated_cost_usd"),
                single_agent_avg_cost=safe_avg(single, "estimated_cost_usd"),
                mosaic_avg_quality=safe_avg(mosaic, "quality_score"),
                single_agent_avg_quality=safe_avg(single, "quality_score"),
            )
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: aggregate] -> "
                f"Aggregation failed; n_records={len(records)}. Error: {exc}"
            )
            raise


# ---------------------------------------------------------------------------
# Visualisation (optional — requires matplotlib)
# ---------------------------------------------------------------------------

def plot_cost_vs_quality(records: List[QueryRecord], out_dir: Path = RESULTS_DIR) -> None:
    try:
        import matplotlib.pyplot as plt  # type: ignore

        mosaic = [r for r in records if r.pipeline == "mosaic"]
        single = [r for r in records if r.pipeline == "single_agent"]

        fig, ax = plt.subplots(figsize=(9, 6))
        ax.scatter(
            [r.estimated_cost_usd for r in mosaic],
            [r.quality_score for r in mosaic],
            label="MOSAIC", color="#6C63FF", alpha=0.75, s=60,
        )
        ax.scatter(
            [r.estimated_cost_usd for r in single],
            [r.quality_score for r in single],
            label="Single-Agent RAG", color="#FF6584", alpha=0.75, s=60,
        )
        ax.set_xlabel("Estimated Cost (USD)")
        ax.set_ylabel("Quality Score (F1)")
        ax.set_title("MOSAIC: API Cost vs. Answer Quality")
        ax.legend()
        ax.grid(True, linestyle="--", alpha=0.5)
        fig.tight_layout()

        plot_path = out_dir / f"cost_vs_quality_{int(time.time())}.png"
        fig.savefig(plot_path, dpi=150)
        logger.info(f"Plot saved → {plot_path}")
    except ImportError:
        logger.warning(
            "[CostAnalysis] matplotlib not installed; skipping plot. "
            "Run: pip install matplotlib"
        )
    except Exception as exc:
        logger.error(
            f"[MOSAIC-ERR][Component: CostAnalysis][Func: plot_cost_vs_quality] -> "
            f"Plot generation failed. Error: {exc}"
        )


# ---------------------------------------------------------------------------
# Output & CLI
# ---------------------------------------------------------------------------

def print_report(r: CostQualityReport) -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print("  MOSAIC API Cost vs. Quality Analysis")
    print(sep)
    print(f"  Total queries            : {r.total_queries}")
    print(f"  Total estimated cost     : ${r.total_cost_usd:.6f}")
    print(f"  Avg cost / query         : ${r.avg_cost_per_query_usd:.8f}")
    print(f"  Avg tokens / query       : {r.avg_tokens_per_query}")
    print(f"  Avg quality score (F1)   : {r.avg_quality_score:.4f}")
    print(f"  Cost / quality unit      : ${r.cost_per_unit_quality:.8f}")
    print(f"  ─── MOSAIC pipeline ─────────────────────────────────")
    print(f"  Avg cost                 : ${r.mosaic_avg_cost:.8f}")
    print(f"  Avg quality              : {r.mosaic_avg_quality:.4f}")
    print(f"  ─── Single-Agent RAG ────────────────────────────────")
    print(f"  Avg cost                 : ${r.single_agent_avg_cost:.8f}")
    print(f"  Avg quality              : {r.single_agent_avg_quality:.4f}")
    print(sep + "\n")


def save_results(records: List[QueryRecord], report: CostQualityReport,
                 out_dir: Path = RESULTS_DIR) -> None:
    try:
        tag = int(time.time())
        (out_dir / f"cost_{tag}_records.json").write_text(
            json.dumps([asdict(r) for r in records], indent=2), encoding="utf-8")
        (out_dir / f"cost_{tag}_report.json").write_text(
            json.dumps(asdict(report), indent=2), encoding="utf-8")
        logger.info(f"Cost results saved → {out_dir}")
    except Exception as exc:
        logger.error(
            f"[MOSAIC-ERR][Component: CostAnalysis][Func: save_results] -> "
            f"Write failed for '{out_dir}'. Error: {exc}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MOSAIC API Cost vs. Quality analysis.")
    parser.add_argument("--input", type=Path,
                        help="Path to accuracy_eval raw JSON output.")
    parser.add_argument("--samples", type=int, default=50,
                        help="Number of synthetic samples (if --input not provided).")
    parser.add_argument("--model", default="gemini-1.5-pro",
                        choices=list(PRICING.keys()),
                        help="LLM model name for pricing lookup.")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--plot", action="store_true",
                        help="Generate cost vs quality scatter plot (needs matplotlib).")
    args = parser.parse_args()

    estimator = TokenEstimator()
    analyzer  = CostAnalyzer(estimator, model=args.model)

    if args.input:
        records = analyzer.build_from_file(args.input)
    else:
        logger.info(f"Using synthetic data ({args.samples} samples).")
        records = analyzer.build_from_synthetic(args.samples)

    report = analyzer.aggregate(records)
    print_report(report)

    if args.save:
        save_results(records, report)
    if args.plot:
        plot_cost_vs_quality(records)


if __name__ == "__main__":
    main()
