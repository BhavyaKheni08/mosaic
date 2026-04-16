import inspect
from functools import wraps
from datetime import datetime
from typing import Any, Callable

class AuditorError(Exception):
    """Base exception for auditor operations."""
    pass

class AuditorGraphConnectionError(AuditorError):
    """Raised when interaction with Graph DB fails."""
    pass

class AuditorLLMError(AuditorError):
    """Raised when Local LLM reasoning fails."""
    pass

class AuditorDecayCalculationError(AuditorError):
    """Raised when decay calculation fails."""
    pass

def log_telemetry(component: str, message: str) -> None:
    """Standardized telemetry logger for the Auditor module."""
    timestamp = datetime.utcnow().isoformat() + "Z"
    print(f"[{timestamp}] [AUDITOR][{component}] {message}")

def with_fallback(fallback_value: Any):
    """
    Decorator to enforce try-except fallback architecture for critical node processing.
    Ensures that failures return a safe fallback value and log an error with the node_id.
    """
    def decorator(func: Callable):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    func_name = func.__name__
                    node_id = kwargs.get('node_id', 'UNKNOWN_NODE')
                    msg = f"Error in {func_name} for Node {node_id}: {str(e)}"
                    log_telemetry("ERROR", msg)
                    return fallback_value
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    func_name = func.__name__
                    node_id = kwargs.get('node_id', 'UNKNOWN_NODE')
                    msg = f"Error in {func_name} for Node {node_id}: {str(e)}"
                    log_telemetry("ERROR", msg)
                    return fallback_value
            return sync_wrapper
    return decorator
