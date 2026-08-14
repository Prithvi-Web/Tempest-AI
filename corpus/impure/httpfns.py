"""10 HTTP-client functions — real-world idioms over urllib (the v1 intercepted NET surface).

Each docstring names the real-world pattern it replicates (ADR-0010). Every function takes
`base_url` so the corpus harness can point it at a loopback server during record."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def fetch_user_name(base_url: str) -> str:
    """Pattern: typical JSON API client (gh/gitlab CLI user lookup)."""
    with urlopen(base_url + "/api/user") as resp:
        return str(json.loads(resp.read().decode())["name"])


def check_health(base_url: str) -> bool:
    """Pattern: Kubernetes-style readiness probe."""
    with urlopen(base_url + "/health") as resp:
        return resp.status == 200


def fetch_with_user_agent(base_url: str) -> str:
    """Pattern: polite crawler setting a User-Agent header."""
    req = Request(base_url + "/robots.txt", headers={"User-Agent": "tempest-corpus/1.0"})
    with urlopen(req) as resp:
        return resp.read().decode()


def paginate_two_pages(base_url: str) -> list[str]:
    """Pattern: REST pagination loop (first two pages)."""
    items: list[str] = []
    for page in (1, 2):
        with urlopen(f"{base_url}/items?page={page}") as resp:
            items.extend(json.loads(resp.read().decode())["items"])
    return items


def download_size(base_url: str) -> int:
    """Pattern: artifact fetcher reporting byte counts."""
    with urlopen(base_url + "/artifact.bin") as resp:
        return len(resp.read())


def fetch_primary_or_fallback(base_url: str, use_primary: bool) -> str:
    """Pattern: feature-flagged endpoint selection."""
    path = "/v2/data" if use_primary else "/v1/data"
    with urlopen(base_url + path) as resp:
        return resp.read().decode()


def count_config_lines(base_url: str) -> int:
    """Pattern: remote config file parsing (line-oriented)."""
    with urlopen(base_url + "/config.txt") as resp:
        return len(resp.read().decode().splitlines())


def retry_on_404(base_url: str) -> str:
    """Pattern: fallback retry after an HTTP error (mirrors requests' retry adapters)."""
    try:
        with urlopen(base_url + "/flaky") as resp:
            return resp.read().decode()
    except HTTPError:
        with urlopen(base_url + "/stable") as resp:
            return resp.read().decode()


def double_read_same_endpoint(base_url: str) -> tuple[str, str]:
    """Pattern: read-verify sequence hitting the same endpoint twice (ordinal keying)."""
    with urlopen(base_url + "/token") as resp:
        first = resp.read().decode()
    with urlopen(base_url + "/token") as resp:
        second = resp.read().decode()
    return first, second


def query_echo(base_url: str, term: str) -> str:
    """Pattern: search endpoint with a query parameter."""
    with urlopen(f"{base_url}/echo?q={term}") as resp:
        return resp.read().decode()
