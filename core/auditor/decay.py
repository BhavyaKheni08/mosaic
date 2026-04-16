import math
from datetime import datetime, timezone
from typing import Optional
from .models import ClaimType
from .utils import log_telemetry, AuditorDecayCalculationError, with_fallback

class DecayConfig:
    """
    Configuration mapping claim types to their decay lambda constants.
    Lambda represents the decay rate per hour.
    """
    LAMBDAS = {
        ClaimType.STATIC_FACT: 0.00001,      # decays very slowly
        ClaimType.CURRENT_EVENT: 0.05,       # decays quickly
        ClaimType.RESEARCH_CLAIM: 0.01,      # decays moderately
        ClaimType.USER_ASSERTION: 0.005      # decays moderately slowly
    }

    @classmethod
    def get_lambda(cls, claim_type: ClaimType) -> float:
        return cls.LAMBDAS.get(claim_type, cls.LAMBDAS[ClaimType.STATIC_FACT])

@with_fallback(fallback_value=None)
def calculate_decayed_confidence(
    stored_confidence: float, 
    last_updated: datetime, 
    claim_type: ClaimType, 
    node_id: str = "UNKNOWN_NODE"
) -> Optional[float]:
    """
    Applies the exponential decay formula:
    C_t = C_0 * exp(-lambda * delta_t_hours)
    """
    try:
        now = datetime.now(timezone.utc)
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
            
        delta_t_hours = (now - last_updated).total_seconds() / 3600.0
        
        # Ensure delta_t is non-negative
        if delta_t_hours < 0:
            delta_t_hours = 0.0
            
        decay_lambda = DecayConfig.get_lambda(claim_type)
        new_confidence = stored_confidence * math.exp(-decay_lambda * delta_t_hours)
        
        log_telemetry(
            "DECAY", 
            f"Recalculating Node {node_id}: Confidence {stored_confidence:.4f} -> {new_confidence:.4f} (dt={delta_t_hours:.2f}h)"
        )
        return new_confidence
    except Exception as e:
        raise AuditorDecayCalculationError(f"Failed to calculate decay: {str(e)}")
