"""10 time/random functions — real-world idioms over the CLOCK and RANDOM surfaces."""

import os
import random
import time
import uuid
from datetime import datetime


def session_token(n: int) -> str:
    """Pattern: secrets-style opaque token."""
    return os.urandom(n).hex()


def request_id() -> str:
    """Pattern: distributed-tracing request id."""
    return str(uuid.uuid4())


def jittered_delay(base: float) -> float:
    """Pattern: exponential-backoff jitter (requests/urllib3 retry)."""
    return base + random.uniform(0.0, 1.0)


def pick_variant(variants: list[str]) -> str:
    """Pattern: A/B test bucket assignment."""
    return random.choice(variants)


def shuffled_copy(xs: list[int]) -> list[int]:
    """Pattern: deck shuffle / randomized worklist."""
    copy = list(xs)
    random.shuffle(copy)
    return copy


def cache_key_epoch() -> int:
    """Pattern: coarse cache-busting key from wall clock."""
    return int(time.time())


def log_timestamp() -> str:
    """Pattern: ISO log line timestamp."""
    return datetime.now().isoformat()


def monotonic_pair_ordered() -> bool:
    """Pattern: elapsed-time guard (t1 must not precede t0)."""
    t0 = time.monotonic()
    t1 = time.monotonic()
    return t1 >= t0


def roll_dice(n: int) -> int:
    """Pattern: game logic / property-test seed material."""
    return sum(random.randint(1, 6) for _ in range(n))


def expiry_deadline(ttl_seconds: int) -> float:
    """Pattern: TTL cache expiry computation."""
    return time.time() + ttl_seconds
