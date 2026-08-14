"""Run-event shapes: the plain-JSON lifecycle ledger the desktop polls beside run status.

Rows are written through `tempest_api.ledger.append_run_event`, so every event carries the
`{stage, level, message}` the UI renders. These are display strings, not engine vocabulary —
engine enums stay defined once in `tempest.model` (CLAUDE.md §9).
"""

from datetime import datetime

from pydantic import BaseModel


class RunEventOut(BaseModel):
    ts: datetime
    stage: str
    level: str
    message: str
