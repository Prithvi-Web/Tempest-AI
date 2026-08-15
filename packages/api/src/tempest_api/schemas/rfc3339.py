"""RFC 3339 wire format for every API datetime (Boundary B honesty).

The published contract is `format: date-time` — RFC 3339 requires an explicit UTC offset,
and the desktop's dev-mode schema validation enforces it live. Rows carry naive-UTC
datetimes by convention (ADR-0009 `utcnow`), so bare serialization would emit offset-less
strings and violate the very schema we generate. `UtcMoment` closes that gap in one place:
naive values are stamped as the UTC they already are, aware values normalize to UTC, and
the JSON Schema stays the exact `{"type": "string", "format": "date-time"}` the generators
already publish (pinned via WithJsonSchema so the drift gate sees no movement).
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer, WithJsonSchema


def rfc3339_utc(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


UtcMoment = Annotated[
    datetime,
    PlainSerializer(rfc3339_utc, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]
