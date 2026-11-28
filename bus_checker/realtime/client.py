"""HTTP access to the AT realtime API with bounded retries."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bus_checker import __version__
from bus_checker.config import Settings

MAX_PAYLOAD_BYTES = 64 * 1024 * 1024


class FetchError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Fetched:
    feed: str
    content: bytes
    status_code: int
    received_at: datetime
    elapsed_sec: float


def make_session(settings: Settings) -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": f"bus-checker/{__version__}",
        }
    )
    return session


def fetch_feed(session: requests.Session, settings: Settings, feed: str) -> Fetched:
    key = settings.require_api_key()
    url = settings.feed_urls[feed]
    started = time.monotonic()
    try:
        response = session.get(
            url,
            headers={"Ocp-Apim-Subscription-Key": key},
            timeout=(10, settings.http_timeout),
            stream=True,
        )
    except requests.RequestException as error:
        raise FetchError(f"{type(error).__name__} while requesting {feed}") from None
    with response:
        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code} from {feed}", response.status_code)
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=256 * 1024):
            size += len(chunk)
            if size > MAX_PAYLOAD_BYTES:
                raise FetchError(f"{feed} payload exceeds {MAX_PAYLOAD_BYTES} bytes", 200)
            chunks.append(chunk)
    return Fetched(
        feed=feed,
        content=b"".join(chunks),
        status_code=response.status_code,
        received_at=datetime.now(UTC),
        elapsed_sec=time.monotonic() - started,
    )
