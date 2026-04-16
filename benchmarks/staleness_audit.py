"""
staleness_audit.py
==================
MOSAIC Phase 7 — Benchmark Suite: Staleness / Time-to-Correction Audit

Seeds the MOSAIC knowledge graph with deliberately outdated facts, then
measures how long the Temporal Decay + Auditor Agent takes to detect and
correct each seeded claim (time-to-correction, TTC).

Usage:
    python staleness_audit.py --seeds 20 --poll-interval 5
    python staleness_audit.py --dry-run   (simulation mode without live Neo4j)

Error convention:
    [MOSAIC-ERR][Component: StalenessAudit][Func: <name>] -> <message>
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mosaic.benchmarks.staleness")

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class StaleSeed:
    """A single seeded-outdated fact injected into the knowledge graph."""
    node_id: str
    claim_text: str
    outdated_value: str
    correct_value: str
    claim_type: str               # e.g. "DRUG_DOSAGE", "REGULATION", "STATISTIC"
    seeded_at: float = field(default_factory=time.time)
    detected_at: Optional[float] = None
    corrected_at: Optional[float] = None
    ttc_seconds: Optional[float] = None       # time-to-correction
    ttd_seconds: Optional[float] = None       # time-to-detection
    final_status: str = "PENDING"             # PENDING | DETECTED | CORRECTED | TIMEOUT


@dataclass
class AuditReport:
    """Aggregated TTC / TTD statistics."""
    total_seeds: int
    corrected: int
    detected_only: int
    timed_out: int
    avg_ttc_seconds: Optional[float]
    min_ttc_seconds: Optional[float]
    max_ttc_seconds: Optional[float]
    avg_ttd_seconds: Optional[float]
    correction_rate: float


# ---------------------------------------------------------------------------
# Seed Templates
# ---------------------------------------------------------------------------

SEED_TEMPLATES = [
    {"claim": "Ibuprofen max daily dose is 2400 mg.",      "outdated": "2400 mg",   "correct": "3200 mg",  "type": "DRUG_DOSAGE"},
    {"claim": "GDPR was enacted in 2016.",                 "outdated": "2016",      "correct": "2018",     "type": "REGULATION"},
    {"claim": "Global CO2 concentration is 380 ppm.",      "outdated": "380 ppm",   "correct": "421 ppm",  "type": "STATISTIC"},
    {"claim": "Python 3.10 is the latest stable release.", "outdated": "3.10",      "correct": "3.12",     "type": "TECH_VERSION"},
    {"claim": "The WHO recommends 6000 steps per day.",    "outdated": "6000",      "correct": "8000",     "type": "HEALTH_GUIDELINE"},
    {"claim": "Bitcoin's all-time high is $69,000.",       "outdated": "$69,000",   "correct": "$99,000+", "type": "MARKET_DATA"},
    {"claim": "GPT-3 has 175B parameters.",                "outdated": "175B",      "correct": "~175B GPT-3 (latest GPT-4 varies)", "type": "TECH_FACT"},
    {"claim": "The Eiffel Tower is 300 m tall.",           "outdated": "300 m",     "correct": "330 m",    "type": "PHYSICAL_FACT"},
    {"claim": "The human genome has ~30,000 genes.",       "outdated": "30,000",    "correct": "~20,000",  "type": "BIOLOGY"},
    {"claim": "Average US life expectancy is 79 years.",   "outdated": "79",        "correct": "77",       "type": "STATISTIC"},
]


def generate_seeds(n: int) -> List[StaleSeed]:
    """Generate `n` StaleSeed instances, cycling through templates."""
    seeds = []
    for i in range(n):
        tpl = SEED_TEMPLATES[i % len(SEED_TEMPLATES)]
        seeds.append(StaleSeed(
            node_id=f"seed-{uuid.uuid4().hex[:8]}",
            claim_text=tpl["claim"],
            outdated_value=tpl["outdated"],
            correct_value=tpl["correct"],
            claim_type=tpl["type"],
        ))
    return seeds


# ---------------------------------------------------------------------------
# Graph Seeder
# ---------------------------------------------------------------------------

class GraphSeeder:
    """Injects stale nodes into Neo4j (or simulates injection in dry-run)."""

    COMPONENT = "GraphSeeder"

    def __init__(self, neo4j_uri: str, neo4j_user: str, neo4j_password: str,
                 dry_run: bool = False) -> None:
        self.uri = neo4j_uri
        self.user = neo4j_user
        self.password = neo4j_password
        self.dry_run = dry_run
        self._driver: Any = None

    def connect(self) -> None:
        if self.dry_run:
            logger.info("[GraphSeeder.connect] DRY-RUN mode — no Neo4j connection.")
            return
        try:
            from neo4j import GraphDatabase  # type: ignore
            self._driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            self._driver.verify_connectivity()
            logger.info(f"[GraphSeeder.connect] Connected to Neo4j at {self.uri}.")
        except ImportError:
            logger.error(
                "[MOSAIC-ERR][Component: GraphSeeder][Func: connect] -> "
                "neo4j driver not installed; Run: pip install neo4j. "
                "Switching to dry-run mode."
            )
            self.dry_run = True
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: connect] -> "
                f"Failed to connect to Neo4j at {self.uri}; "
                f"Ensure Neo4j is running on port 7687. Error: {exc}"
            )
            self.dry_run = True

    def seed(self, seed: StaleSeed) -> bool:
        """Write one stale claim node to the graph; return True on success."""
        if self.dry_run:
            logger.info(f"[GraphSeeder.seed] DRY-RUN seeded: {seed.node_id}")
            return True
        try:
            cypher = (
                "MERGE (n:Claim {node_id: $node_id}) "
                "SET n.claim_text = $claim_text, "
                "    n.claim_type = $claim_type, "
                "    n.value      = $outdated_value, "
                "    n.last_updated = datetime() - duration('P2Y'), "
                "    n.is_stale   = true "
                "RETURN n.node_id"
            )
            with self._driver.session() as session:
                session.run(
                    cypher,
                    node_id=seed.node_id,
                    claim_text=seed.claim_text,
                    claim_type=seed.claim_type,
                    outdated_value=seed.outdated_value,
                )
            logger.info(f"[GraphSeeder.seed] Seeded node {seed.node_id}.")
            return True
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: seed] -> "
                f"Failed to seed node_id={seed.node_id}; "
                f"Check Qdrant port 6333 and Neo4j port 7687. Error: {exc}"
            )
            return False

    def close(self) -> None:
        if self._driver:
            try:
                self._driver.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Status Poller
# ---------------------------------------------------------------------------

class AuditorStatusPoller:
    """Polls the MOSAIC auditor API to check whether seeded nodes are corrected."""

    COMPONENT = "AuditorStatusPoller"

    def __init__(self, endpoint: str = "http://localhost:8000", dry_run: bool = False) -> None:
        self.endpoint = endpoint
        self.dry_run = dry_run

    def check_node(self, node_id: str, elapsed: float) -> str:
        """Return 'CORRECTED', 'DETECTED', or 'PENDING'."""
        if self.dry_run:
            # Simulate: detected after 10 s, corrected after 20 s
            if elapsed >= 20:
                return "CORRECTED"
            if elapsed >= 10:
                return "DETECTED"
            return "PENDING"
        try:
            import httpx  # type: ignore
            resp = httpx.get(
                f"{self.endpoint}/auditor/node/{node_id}",
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json().get("status", "PENDING").upper()
        except ImportError:
            return "PENDING"
        except Exception as exc:
            logger.warning(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: check_node] -> "
                f"Poll failed for node_id={node_id}; "
                f"Ensure MOSAIC API is running at {self.endpoint}. Error: {exc}"
            )
            return "PENDING"


# ---------------------------------------------------------------------------
# Audit Runner
# ---------------------------------------------------------------------------

class StalenessAuditor:
    """Orchestrates seeding → polling → TTC measurement."""

    COMPONENT = "StalenessAuditor"

    def __init__(
        self,
        seeder: GraphSeeder,
        poller: AuditorStatusPoller,
        poll_interval_s: float = 5.0,
        timeout_s: float = 300.0,
    ) -> None:
        self.seeder = seeder
        self.poller = poller
        self.poll_interval = poll_interval_s
        self.timeout = timeout_s

    def run(self, seeds: List[StaleSeed]) -> AuditReport:
        # Phase 1: seed all nodes
        active: List[StaleSeed] = []
        for s in seeds:
            ok = self.seeder.seed(s)
            if ok:
                s.seeded_at = time.time()
                active.append(s)

        logger.info(f"[StalenessAuditor] Seeded {len(active)}/{len(seeds)} nodes. Polling …")

        # Phase 2: poll until all resolved or timeout
        pending = [s for s in active]
        while pending:
            time.sleep(self.poll_interval)
            still_pending = []
            for s in pending:
                elapsed = time.time() - s.seeded_at
                try:
                    status = self.poller.check_node(s.node_id, elapsed)
                except Exception as exc:
                    logger.error(
                        f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: run] -> "
                        f"Polling error for node_id={s.node_id}. Error: {exc}"
                    )
                    status = "PENDING"

                if status == "DETECTED" and s.ttd_seconds is None:
                    s.ttd_seconds = elapsed
                    s.detected_at = time.time()
                    s.final_status = "DETECTED"
                    logger.info(f"  DETECTED  {s.node_id} @ {elapsed:.1f}s")

                if status == "CORRECTED":
                    s.corrected_at = time.time()
                    s.ttc_seconds = elapsed
                    if s.ttd_seconds is None:
                        s.ttd_seconds = elapsed
                    s.final_status = "CORRECTED"
                    logger.info(f"  CORRECTED {s.node_id} @ {elapsed:.1f}s")
                    continue  # removed from pending

                if elapsed >= self.timeout:
                    s.final_status = "TIMEOUT"
                    logger.warning(f"  TIMEOUT   {s.node_id}")
                    continue

                still_pending.append(s)

            pending = still_pending
            logger.info(f"[StalenessAuditor] Pending: {len(pending)}")

        return self._aggregate(active)

    def _aggregate(self, seeds: List[StaleSeed]) -> AuditReport:
        try:
            n = len(seeds)
            corrected  = [s for s in seeds if s.final_status == "CORRECTED"]
            detected   = [s for s in seeds if s.final_status == "DETECTED"]
            timed_out  = [s for s in seeds if s.final_status == "TIMEOUT"]

            ttcs = [s.ttc_seconds for s in corrected if s.ttc_seconds is not None]
            ttds = [s.ttd_seconds for s in seeds if s.ttd_seconds is not None]

            return AuditReport(
                total_seeds=n,
                corrected=len(corrected),
                detected_only=len(detected),
                timed_out=len(timed_out),
                avg_ttc_seconds=round(sum(ttcs)/len(ttcs), 2) if ttcs else None,
                min_ttc_seconds=round(min(ttcs), 2) if ttcs else None,
                max_ttc_seconds=round(max(ttcs), 2) if ttcs else None,
                avg_ttd_seconds=round(sum(ttds)/len(ttds), 2) if ttds else None,
                correction_rate=round(len(corrected)/n, 4) if n > 0 else 0.0,
            )
        except Exception as exc:
            logger.error(
                f"[MOSAIC-ERR][Component: {self.COMPONENT}][Func: _aggregate] -> "
                f"Aggregation failed; n_seeds={len(seeds)}. Error: {exc}"
            )
            raise


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def print_report(r: AuditReport) -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print("  MOSAIC Staleness / Time-to-Correction Audit")
    print(sep)
    print(f"  Seeds injected : {r.total_seeds}")
    print(f"  Corrected      : {r.corrected}  (rate: {r.correction_rate:.1%})")
    print(f"  Detected only  : {r.detected_only}")
    print(f"  Timed out      : {r.timed_out}")
    if r.avg_ttc_seconds is not None:
        print(f"  Avg TTC        : {r.avg_ttc_seconds:.1f}s  "
              f"[min={r.min_ttc_seconds:.1f}s  max={r.max_ttc_seconds:.1f}s]")
    else:
        print("  Avg TTC        : N/A (no corrections recorded)")
    if r.avg_ttd_seconds is not None:
        print(f"  Avg TTD        : {r.avg_ttd_seconds:.1f}s")
    print(sep + "\n")


def save_report(seeds: List[StaleSeed], report: AuditReport,
                out_dir: Path = RESULTS_DIR) -> None:
    try:
        tag = int(time.time())
        (out_dir / f"staleness_{tag}_seeds.json").write_text(
            json.dumps([asdict(s) for s in seeds], indent=2), encoding="utf-8")
        (out_dir / f"staleness_{tag}_report.json").write_text(
            json.dumps(asdict(report), indent=2), encoding="utf-8")
        logger.info(f"Staleness audit results saved → {out_dir}")
    except Exception as exc:
        logger.error(
            f"[MOSAIC-ERR][Component: StalenessAudit][Func: save_report] -> "
            f"Write failed for '{out_dir}'. Error: {exc}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MOSAIC Staleness Audit — time-to-correction benchmark.")
    parser.add_argument("--seeds", type=int, default=10,
                        help="Number of outdated facts to seed.")
    parser.add_argument("--poll-interval", type=float, default=5.0,
                        help="Polling frequency in seconds.")
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="Max wait per seed before marking TIMEOUT.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate without live Neo4j / MOSAIC API.")
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="password")
    parser.add_argument("--mosaic-endpoint", default="http://localhost:8000")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    seeds = generate_seeds(args.seeds)

    seeder = GraphSeeder(
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        dry_run=args.dry_run,
    )
    seeder.connect()

    poller = AuditorStatusPoller(endpoint=args.mosaic_endpoint, dry_run=args.dry_run)
    auditor = StalenessAuditor(seeder, poller, args.poll_interval, args.timeout)

    logger.info(f"Starting staleness audit | seeds={args.seeds} dry_run={args.dry_run}")
    report = auditor.run(seeds)
    seeder.close()
    print_report(report)

    if args.save:
        save_report(seeds, report)


if __name__ == "__main__":
    main()
