"""Run-event shapes: the plain-JSON lifecycle ledger the desktop polls beside run status.

Rows are written through `tempest_api.ledger.append_run_event`, so every event carries the
`{stage, level, message}` the UI renders. These are display strings, not engine vocabulary —
engine enums stay defined once in `tempest.model` (CLAUDE.md §9).
"""

from pydantic import BaseModel

from tempest_api.schemas.rfc3339 import UtcMoment


class RunEventOut(BaseModel):
    ts: UtcMoment
    stage: str
    level: str
    message: str
