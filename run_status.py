"""Small, atomic production-stage record, independent of model/API clients."""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo


def write_private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2)
    temporary.replace(path)


class ProductionRun:
    def __init__(self, enabled, state):
        self.enabled = enabled
        self.path = state / 'production-run.json'
        self.record = {}

    def stage(self, stage, **details):
        if self.enabled:
            now = datetime.now(ZoneInfo('America/New_York')).isoformat()
            self.record.setdefault('started_at', now)
            self.record.update(stage=stage, updated_at=now, **details)
            write_private_json(self.path, self.record)

    def __enter__(self):
        self.stage('starting')
        return self

    def __exit__(self, kind, value, traceback):
        if kind:
            self.stage('failed', failed_stage=self.record.get('stage'), error_type=kind.__name__)
        return False
