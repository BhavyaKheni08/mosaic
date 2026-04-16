import sys
import functools
import inspect
from loguru import logger

# Configure loguru to show detailed backtraces and diagnose variables
logger.remove()
logger.add(sys.stdout, colorize=True, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>", backtrace=True, diagnose=True)

def trace_error(func):
    """
    Decorator to wrap functions in a try-except block and log errors using loguru.
    Attempts to extract `session_id` from kwargs or args (assuming it's the first string arg)
    to provide traceability. Logs the function name, line, and file via loguru's built-in diagnose.
    """
    
    def _extract_session_id(*args, **kwargs):
        session_id = kwargs.get('session_id')
        if not session_id:
            for arg in args:
                if isinstance(arg, str) and (len(arg) == 36 or arg.startswith("sess_")):
                    # Simple heuristic for session id if it's a uuid or prefixed
                    session_id = arg
                    break
        return session_id or "UNKNOWN_SESSION"

    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            session_id = _extract_session_id(*args, **kwargs)
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.opt(exception=True).error(f"Error executing {func.__name__} (session_id: {session_id}): {str(e)}")
                raise
        return async_wrapper
    else:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            session_id = _extract_session_id(*args, **kwargs)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.opt(exception=True).error(f"Error executing {func.__name__} (session_id: {session_id}): {str(e)}")
                raise
        return sync_wrapper

