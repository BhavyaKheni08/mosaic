import json
from pathlib import Path
from .models import AuditEvent
from .utils import log_telemetry, AuditorGraphConnectionError

class AuditLogger:
    """
    Specialized logger for recording AuditEvents.
    Writes back to mock Graph system and local audit_trail.json.
    """
    
    def __init__(self, log_dir: str = "/Users/bhavyakheni/Desktop/mosaic/core/auditor"):
        self.log_file = Path(log_dir) / "audit_trail.json"
        
        # Ensure file exists
        if not self.log_file.exists():
            with open(self.log_file, "w") as f:
                json.dump([], f)

    def log_event(self, event: AuditEvent):
        """Logs an event both locally and to the mock graph."""
        self._write_to_disk(event)
        self._write_to_graph_mock(event)
        log_telemetry("LOGGER", f"Logged AuditEvent {event.event_id} for Node {event.node_id}")

    def _write_to_disk(self, event: AuditEvent):
        try:
            with open(self.log_file, "r+") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = []
                data.append(event.model_dump(mode='json'))
                f.seek(0)
                json.dump(data, f, indent=2)
        except Exception as e:
            log_telemetry("ERROR", f"Failed local audit log writing: {str(e)}")

    def _write_to_graph_mock(self, event: AuditEvent):
        """Mock function for Neo4j interaction."""
        try:
            pass # Stub for neo4j action
        except Exception as e:
            raise AuditorGraphConnectionError(f"Failed writing audit event to graph: {str(e)}")
