from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FetchedDocument:
    url: str
    markdown: str


class ContentFetcher(Protocol):
    """Interface shared by future plain HTTP and Firecrawl readers."""

    def fetch(self, url: str) -> FetchedDocument:
        ...


class FetcherNotEnabled(RuntimeError):
    pass


class PlainHttpFetcher:
    """Disabled placeholder for a future allowlisted HTTP implementation."""

    def fetch(self, url: str) -> FetchedDocument:
        raise FetcherNotEnabled("普通网页读取器尚未启用，不会发送网络请求。")


class FirecrawlFetcher:
    """Disabled placeholder; no SDK, API key, or network call is used yet."""

    def fetch(self, url: str) -> FetchedDocument:
        raise FetcherNotEnabled("Firecrawl 读取器尚未启用，不会发送网络请求。")
