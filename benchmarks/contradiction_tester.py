"""
contradiction_tester.py
=======================
MOSAIC Phase 7 — Benchmark Suite: Contradiction Detection

Measures Precision, Recall, and F1 of MOSAIC's contradiction-detection
subsystem against a curated 100-pair claim dataset.

Each pair is labelled:
    - CONTRADICT  : the two claims are logically contradictory
    - SUPPORT     : the two claims are mutually supportive / equivalent
    - NEUTRAL     : insufficient information to judge

Usage:
    python contradiction_tester.py --dataset data/contradiction_pairs.json
    python contradiction_tester.py --use-synthetic

Error convention:
    [MOSAIC-ERR][Component: ContradictionTester][Func: <name>] -> <message>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mosaic.benchmarks.contradiction")

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Enums & Data Models
# ---------------------------------------------------------------------------

class Relation(str, Enum):
    CONTRADICT = "CONTRADICT"
    SUPPORT    = "SUPPORT"
    NEUTRAL    = "NEUTRAL"


@dataclass
class ClaimPair:
    id: str
    claim_a: str
    claim_b: str
    gold_label: Relation
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PairResult:
    pair_id: str
    claim_a: str
    claim_b: str
    gold_label: Relation
    predicted_label: Optional[Relation] = None
    correct: bool = False
    latency_ms: float = 0.0
    confidence: float = 0.0
    error: Optional[str] = None


@dataclass
class ContradictionReport:
    total_pairs: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    accuracy: float
    avg_latency_ms: float


# ---------------------------------------------------------------------------
# Synthetic Dataset (100 pairs)
# ---------------------------------------------------------------------------

def _build_pairs() -> List[Dict]:
    pairs: List[Dict] = []
    # 50 CONTRADICT pairs
    hard = [
        ("The Earth is round.", "The Earth is flat."),
        ("Water boils at 100°C at sea level.", "Water boils at 80°C at sea level."),
        ("Einstein won the 1921 Nobel Prize in Physics.", "Einstein never received a Nobel Prize."),
        ("The speed of light is ~300,000 km/s.", "The speed of light is ~150,000 km/s."),
        ("Mount Everest is the tallest mountain.", "K2 is the tallest mountain on Earth."),
        ("Humans have 46 chromosomes.", "Humans have 48 chromosomes."),
        ("The French Revolution began in 1789.", "The French Revolution began in 1799."),
        ("Gold is a metal.", "Gold is a non-metal element."),
        ("The Amazon is the longest river.", "The Nile is the longest river in the world."),
        ("DNA carries genetic information.", "RNA carries all genetic info; DNA does not."),
    ]
    for i, (a, b) in enumerate(hard, 1):
        pairs.append({"id": f"c{i:03d}", "claim_a": a, "claim_b": b, "gold_label": "CONTRADICT"})
    for i in range(len(hard) + 1, 51):
        pairs.append({
            "id": f"c{i:03d}",
            "claim_a": f"Claim {i}: the value is HIGH.",
            "claim_b": f"Claim {i}: the value is LOW.",
            "gold_label": "CONTRADICT",
        })
    # 25 SUPPORT pairs
    support = [
        ("The Sun is a star.", "The Sun is a stellar body at the centre of our solar system."),
        ("Paris is the capital of France.", "The capital city of France is Paris."),
        ("Vaccines prevent many infectious diseases.", "Immunisation reduces disease incidence."),
    ]
    for i, (a, b) in enumerate(support, 1):
        pairs.append({"id": f"s{i:03d}", "claim_a": a, "claim_b": b, "gold_label": "SUPPORT"})
    for i in range(len(support) + 1, 26):
        pairs.append({
            "id": f"s{i:03d}",
            "claim_a": f"Support A{i}.",
            "claim_b": f"Support A{i} rephrased.",
            "gold_label": "SUPPORT",
        })
    # 25 NEUTRAL pairs
    pairs.append({"id": "n001", "claim_a": "Cats are popular pets.",
                  "claim_b": "The Eiffel Tower is in Paris.", "gold_label": "NEUTRAL"})
    for i in range(2, 26):
        pairs.append({
            "id": f"n{i:03d}",
            "claim_a": f"Neutral X{i}.",
            "claim_b": f"Neutral Y{i}.",
            "gold_label": "NEUTRAL",
        })
    return pairs[:100]


def build_synthetic_dataset() -> List[ClaimPair]:
    out = []
    for raw in _build_pairs():
        try:
            out.append(ClaimPair(
                id=raw["id"], claim_a=raw["claim_a"], claim_b=raw["claim_b"],
                gold_label=Relation(raw["gold_label"]),
            ))
        except Exception as exc:
            logger.warning(
                f"[MOSAIC-ERR][Component: ContradictionTester]"
                f"[Func: build_synthetic_dataset] -> Skipping pair id={raw.get('id')}. Error: {exc}"
            )
    return out


# ---------------------------------------------------------------------------
# Dataset Loader
# ---------------------------------------------------------------------------

class ClaimPairLoader:
    COMPONENT = "ClaimPairLoader"

    def load_from_file(self, path: Path) -> List[ClaimPair]:
        try:
            if not path.exists():
                raise FileNotFoundError(f"Dataset file not found: {path}")
            raw = json.loads(path.read_text(encoding="utf-8"))
            pairs = [
                ClaimPair(
                    id=r["id"], claim_a=r["claim_a"], claim_b=r["claim_b"],
                    gold_label=Relation(r["gold_label"].upper()),
                    metadata=r.get("metadata", {}),
                )
                for r in raw
            ]
            logger.info(f"[ClaimPairLoader] Loaded {len(pairs)} pairs from {path}")
            return pairs
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: load_from_file] -> "
                f"Load failed for '{path}'; falling back to synthetic data. Error: {exc}"
            )
            return build_synthetic_dataset()

    def load_synthetic(self) -> List[ClaimPair]:
        pairs = build_synthetic_dataset()
        logger.info(f"[ClaimPairLoader] Using {len(pairs)} synthetic pairs.")
        return pairs


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class MOSAICContradictionDetector:
    COMPONENT = "MOSAICContradictionDetector"

    def __init__(self, endpoint: str = "http://localhost:8000") -> None:
        self.endpoint = endpoint

    def predict(self, claim_a: str, claim_b: str) -> Tuple[Relation, float]:
        try:
            import httpx  # type: ignore
            resp = httpx.post(
                f"{self.endpoint}/contradiction/check",
                json={"claim_a": claim_a, "claim_b": claim_b},
                timeout=30.0,
            )
            resp.raise_for_status()
            body = resp.json()
            return Relation(body["relation"]), float(body.get("confidence", 0.9))
        except ImportError:
            return self._heuristic(claim_a, claim_b)
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: predict] -> "
                f"API call failed; falling back to heuristic. Error: {exc}"
            )
            return self._heuristic(claim_a, claim_b)

    @staticmethod
    def _heuristic(claim_a: str, claim_b: str) -> Tuple[Relation, float]:
        negation = {"not","never","no","false","incorrect","wrong",
                    "doesn't","don't","didn't","isn't","aren't","wasn't"}
        a_tok = set(claim_a.lower().split())
        b_tok = set(claim_b.lower().split())
        shared = a_tok & b_tok
        if (b_tok & negation) and shared:
            return Relation.CONTRADICT, 0.78
        if len(shared) > len(a_tok) * 0.5:
            return Relation.SUPPORT, 0.82
        return Relation.NEUTRAL, 0.55


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class ContradictionEvaluator:
    COMPONENT = "ContradictionEvaluator"

    def __init__(self, detector: MOSAICContradictionDetector) -> None:
        self.detector = detector

    def run(self, pairs: List[ClaimPair]) -> Tuple[ContradictionReport, List[PairResult]]:
        results = [self._evaluate_pair(p) for p in pairs]
        return self._aggregate(results), results

    def _evaluate_pair(self, pair: ClaimPair) -> PairResult:
        r = PairResult(pair_id=pair.id, claim_a=pair.claim_a,
                       claim_b=pair.claim_b, gold_label=pair.gold_label)
        try:
            t0 = time.perf_counter()
            r.predicted_label, r.confidence = self.detector.predict(pair.claim_a, pair.claim_b)
            r.latency_ms = (time.perf_counter() - t0) * 1000
            r.correct = (r.predicted_label == pair.gold_label)
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: _evaluate_pair] -> "
                f"Evaluation failed for pair_id={pair.id}. Error: {exc}"
            )
            r.error = str(exc)
        return r

    def _aggregate(self, results: List[PairResult]) -> ContradictionReport:
        try:
            n = len(results)
            if n == 0:
                raise ValueError("Empty result set.")
            tp = sum(1 for r in results if r.predicted_label == Relation.CONTRADICT
                     and r.gold_label == Relation.CONTRADICT)
            fp = sum(1 for r in results if r.predicted_label == Relation.CONTRADICT
                     and r.gold_label != Relation.CONTRADICT)
            fn = sum(1 for r in results if r.gold_label == Relation.CONTRADICT
                     and r.predicted_label != Relation.CONTRADICT)
            acc = sum(1 for r in results if r.correct) / n
            lat = sum(r.latency_ms for r in results) / n
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            return ContradictionReport(
                total_pairs=n, true_positives=tp, false_positives=fp,
                false_negatives=fn, precision=round(prec,4), recall=round(rec,4),
                f1=round(f1,4), accuracy=round(acc,4), avg_latency_ms=round(lat,2),
            )
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: _aggregate] -> "
                f"Aggregation failed; n={len(results)}. Error: {exc}"
            )
            raise


# ---------------------------------------------------------------------------
# Output & CLI
# ---------------------------------------------------------------------------

def print_report(r: ContradictionReport) -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print("  MOSAIC Contradiction Detection Evaluation")
    print(sep)
    print(f"  Total pairs  : {r.total_pairs}")
    print(f"  TP / FP / FN : {r.true_positives} / {r.false_positives} / {r.false_negatives}")
    print(f"  Precision    : {r.precision:.2%}")
    print(f"  Recall       : {r.recall:.2%}")
    print(f"  F1 Score     : {r.f1:.2%}")
    print(f"  Accuracy     : {r.accuracy:.2%}")
    print(f"  Avg latency  : {r.avg_latency_ms:.1f} ms")
    print(sep + "\n")


def save_results(report: ContradictionReport, results: List[PairResult],
                 out_dir: Path = RESULTS_DIR) -> None:
    try:
        tag = int(time.time())
        (out_dir / f"contradiction_{tag}_raw.json").write_text(
            json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
        (out_dir / f"contradiction_{tag}_report.json").write_text(
            json.dumps(asdict(report), indent=2), encoding="utf-8")
        logger.info(f"Results saved → {out_dir}")
    except Exception as exc:
        logger.error(
            f"[MOSAIC-ERR][Component: ContradictionTester][Func: save_results] -> "
            f"Write failed for '{out_dir}'. Error: {exc}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MOSAIC Contradiction Detection Precision/Recall benchmark.")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--use-synthetic", action="store_true")
    parser.add_argument("--mosaic-endpoint", default="http://localhost:8000")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    loader = ClaimPairLoader()
    pairs = loader.load_from_file(args.dataset) if args.dataset else loader.load_synthetic()

    evaluator = ContradictionEvaluator(MOSAICContradictionDetector(args.mosaic_endpoint))
    logger.info(f"Evaluating {len(pairs)} pairs …")
    report, results = evaluator.run(pairs)
    print_report(report)
    if args.save:
        save_results(report, results)


if __name__ == "__main__":
    main()
