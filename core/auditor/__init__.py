"""
Auditor Module for Mosaic

This module contains the Temporal Decay and Auditor Agent logic.
It implements exponential decay for knowledge graph nodes and dynamically re-researches 
claims with an embedded LLM.
"""

from .utils import log_telemetry
from .decay import DecayConfig, calculate_decayed_confidence
from .models import AuditEvent, StaleNode, ClaimType
from .logger import AuditLogger
from .agent import AuditorAgent

__all__ = [
    "log_telemetry",
    "DecayConfig",
    "calculate_decayed_confidence",
    "AuditEvent",
    "StaleNode",
    "ClaimType",
    "AuditLogger",
    "AuditorAgent"
]
