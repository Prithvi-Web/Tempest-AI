"""Cursor pagination envelope (master spec §8): `{items, next_cursor}`.

The cursor is opaque to clients. `next_cursor` is null on the last page. A malformed cursor is a
`VALIDATION_ERROR`, not a silent empty page.
"""

import base64
import binascii

from pydantic import BaseModel

_PREFIX = "v1:"


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


def encode_cursor(last_id: int) -> str:
    return base64.urlsafe_b64encode(f"{_PREFIX}{last_id}".encode()).decode("ascii")


def decode_cursor(cursor: str) -> int:
    """Returns the id encoded in the cursor. Raises ValueError for anything malformed."""
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise ValueError(f"malformed cursor: {cursor!r}") from exc
    if not decoded.startswith(_PREFIX):
        raise ValueError(f"malformed cursor: {cursor!r}")
    try:
        return int(decoded.removeprefix(_PREFIX))
    except ValueError as exc:
        raise ValueError(f"malformed cursor: {cursor!r}") from exc
