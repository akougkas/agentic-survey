from dataclasses import dataclass


@dataclass(slots=True)
class FetchedDocument:
    source: str
    content: str


class Fetcher:
    async def fetch_url(self, url: str) -> FetchedDocument:
        return FetchedDocument(source=url, content="")
