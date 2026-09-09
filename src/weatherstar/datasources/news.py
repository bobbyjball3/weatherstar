"""Local news datasource: city label + headline sourcing for the news screens.

Headlines come from the webz.io News Context API when configured (an ``api_key``
plus a ``news_query``).  With no configuration the datasource degrades to no
headlines and the screen shows its empty-state message.  City naming defers to
the weather datasource (via the screen), so this datasource only supplies
headlines.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import ClassVar

import requests
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from weatherstar.datasources.base import Datasource
from weatherstar.registry import plugin


class Headline(BaseModel):
    """A single headline with its source URL."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", description="Headline text.")
    url: str = Field(default="", description="Source link.")


@plugin
class LocalNewsDatasource(Datasource):
    name = "local_news"

    _default_cache_ttl: ClassVar[int] = 3600
    _api_endpoint: ClassVar[str] = "https://api.webz.io/api/news/context"

    api_key: SecretStr | None = Field(
        default=None,
        description=("Webz.io API key (sent as a Bearer token; empty disables live news)."),
    )

    news_query: str = Field(
        default="",
        description="Free-text news search query (e.g. 'News in Carmel, Indiana').",
    )

    story_count: int = Field(
        default=10,
        description="The number of stories to retrieve from webz (default 10).",
    )

    languages: list[str] = Field(
        default=["english"],
        description="A list of languages to use for news story searches.",
    )

    countries: list[str] = Field(
        default=["US"],
        description="List of two-letter country codes to use for news story searches.",
    )

    news_categories: list[str] = Field(
        default=["Crime, Law and Justice"],
        description="List of categories to use when searching news stories from webz.io.",
    )

    news_day_count: int = Field(
        default=10,
        description="Number of days to look in the past for news stories.",
    )

    def _apply_auth(self, session: requests.Session) -> None:
        """Authenticate with a Bearer token instead of the default header."""
        if self.api_key:
            session.headers.update({"Authorization": f"Bearer {self.api_key.get_secret_value()}"})

    def _get_headlines(self) -> list[Headline]:
        """Fetch headlines from the webz.io context endpoint ([] when disabled)."""
        if not self.news_query or not self.api_key:
            return []

        published_from = datetime.now(timezone.utc) - timedelta(days=self.news_day_count)
        body = {
            "query": self.news_query,
            "k": self.story_count,
            "filters": {
                "published_from": published_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "language": self.languages,
                "country": self.countries,
                "category": self.news_categories,
            },
        }
        try:
            response = self._session_for().post(self._api_endpoint, json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            self._log.warning("news_fetch_failed", error=str(exc))
            return []

        results = payload.get("results") if isinstance(payload, dict) else None
        headlines: list[Headline] = []
        for result in results or []:
            article = result.get("article") if isinstance(result, dict) else None
            if not isinstance(article, dict):
                continue
            title = str(article.get("title") or "").strip()
            url = str(article.get("url") or "")
            if title:
                headlines.append(Headline(title=title, url=url))
        return headlines

    def city_name(self, lat: float, lon: float) -> str:
        """Return a city label; empty lets the screen fall back to weather data."""
        return ""

    def headlines(self, lat: float, lon: float) -> list[Headline]:
        """Return the local headlines (most recent first)."""
        key = self._cache_key("local_news")
        cached = self.cache_get(key)
        if cached is not None:
            return cached

        headlines = self._get_headlines()
        self.cache_set(key, headlines)
        return headlines
