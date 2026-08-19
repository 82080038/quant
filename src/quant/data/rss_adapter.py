"""RSS feed adapter for Indonesian financial news.

Fetches news from:
  - CNBC Indonesia (https://www.cnbcindonesia.com/rss)
  - Detik Finance (https://finance.detik.com/rss)
  - Kontan (https://www.kontan.co.id/rss)

Stores headlines in news_sentiment table with basic sentiment scoring.
When IndoBERT is available (B2), sentiment will be re-scored by the NLP model.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlparse

import pandas as pd
import requests
from sqlalchemy import text

from quant.core.db import get_db

logger = logging.getLogger(__name__)

__all__ = ["RSSFeedAdapter", "RSSItem", "FEED_SOURCES"]


@dataclass
class RSSItem:
    """A single RSS feed item."""

    title: str
    url: str
    published: datetime
    source: str
    description: str = ""
    tickers: list[str] = None


# RSS feed URLs for Indonesian financial news
FEED_SOURCES: dict[str, list[str]] = {
    "cnbc_indonesia": [
        "https://www.cnbcindonesia.com/market/rss",
        "https://www.cnbcindonesia.com/investment/rss",
        "https://www.cnbcindonesia.com/news/rss",
    ],
    "detik_finance": [
        "https://finance.detik.com/rss/market",
        "https://finance.detik.com/rss",
    ],
    "kontan": [
        "https://www.kontan.co.id/rss/market",
        "https://www.kontan.co.id/rss/investasi",
        "https://www.kontan.co.id/rss/news",
    ],
}

# Simple positive/negative word lists for Indonesian financial news
POSITIVE_WORDS = {
    "naik", "unggul", "untung", "rally", "bullish", "gain", "rebound",
    "positif", "optimis", "tumbuh", "melonjak", "menguat", "merangkak",
    "beli", "akumulasi", "breakout", "support", "lowongan",
    "dividen", "buyback", "upgrade", "target",
}

NEGATIVE_WORDS = {
    "turun", "rugi", "jatuh", "bearish", "sell", "jual", "distribusi",
    "negatif", "pesimis", "terpuruk", "melemah", "tergelincir", "anjlok",
    "korban", "gagal", "loss", "cut", "stop", "breakdown", "resistensi",
    "downgrade", "sanksi", "pelanggaran", "anomali", "suspend",
}


class RSSFeedAdapter:
    """RSS feed adapter for Indonesian financial news.

    Usage::

        adapter = RSSFeedAdapter()
        items = adapter.fetch_all()
        adapter.store(items)
    """

    def __init__(self, session=None, timeout: int = 15):
        self._session = session
        self._timeout = timeout
        self._owns_session = session is None

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
        return self._session

    def close(self):
        if self._owns_session and self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass

    def fetch_feed(self, url: str, source: str) -> list[RSSItem]:
        """Fetch and parse a single RSS feed."""
        try:
            resp = requests.get(url, timeout=self._timeout, headers={
                "User-Agent": "Mozilla/5.0 (quant trading system)"
            })
            resp.raise_for_status()
            root = ET.fromstring(resp.content)

            items = []
            # Handle both RSS and Atom formats
            if root.tag == "rss":
                for item in root.findall(".//item"):
                    title = self._get_text(item, "title")
                    link = self._get_text(item, "link")
                    pub_date = self._parse_date(self._get_text(item, "pubDate"))
                    desc = self._get_text(item, "description")
                    if title and link:
                        items.append(RSSItem(
                            title=title,
                            url=link,
                            published=pub_date or datetime.utcnow(),
                            source=source,
                            description=desc or "",
                            tickers=[],
                        ))
            elif root.tag == "{http://www.w3.org/2005/Atom}feed":
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for entry in root.findall(".//atom:entry", ns):
                    title = self._get_text_ns(entry, "atom:title", ns)
                    link_el = entry.find("atom:link", ns)
                    link = link_el.get("href") if link_el is not None else ""
                    pub_date = self._parse_date(self._get_text_ns(entry, "atom:updated", ns))
                    summary = self._get_text_ns(entry, "atom:summary", ns)
                    if title and link:
                        items.append(RSSItem(
                            title=title,
                            url=link,
                            published=pub_date or datetime.utcnow(),
                            source=source,
                            description=summary or "",
                            tickers=[],
                        ))
            logger.info("Fetched %d items from %s (%s)", len(items), url, source)
            return items
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)
            return []

    def fetch_all(self, sources: Optional[list[str]] = None) -> list[RSSItem]:
        """Fetch all RSS feeds from configured sources."""
        all_items = []
        source_map = FEED_SOURCES if sources is None else {
            s: FEED_SOURCES.get(s, []) for s in sources
        }
        for source_name, urls in source_map.items():
            for url in urls:
                items = self.fetch_feed(url, source_name)
                all_items.extend(items)
        logger.info("Total fetched: %d items from %d sources", len(all_items), len(source_map))
        return all_items

    def extract_tickers(self, text: str, known_tickers: Optional[set[str]] = None) -> list[str]:
        """Extract IDX ticker mentions from text.

        Looks for patterns like BBCA, BBRI, TLKM, or BBCA.JK.
        """
        # Pattern: 4-letter uppercase codes common in IDX
        pattern = r'\b([A-Z]{4})\b\.?\s*(?:JK)?'
        candidates = re.findall(pattern, text.upper())

        if known_tickers:
            return [c for c in candidates if c in known_tickers or c + ".JK" in known_tickers]
        return list(set(candidates))

    def score_sentiment(self, text: str) -> tuple[float, str]:
        """Simple keyword-based sentiment scoring.

        Returns (score, label) where score is in [-1, 1] and
        label is 'positive', 'negative', or 'neutral'.
        """
        words = set(text.lower().split())
        pos_count = sum(1 for w in POSITIVE_WORDS if w in words)
        neg_count = sum(1 for w in NEGATIVE_WORDS if w in words)

        total = pos_count + neg_count
        if total == 0:
            return 0.0, "neutral"

        score = (pos_count - neg_count) / total
        if score > 0.1:
            return score, "positive"
        elif score < -0.1:
            return score, "negative"
        return 0.0, "neutral"

    def store(self, items: list[RSSItem]) -> int:
        """Store RSS items in news_sentiment table.

        Returns number of rows inserted.
        """
        # Get known tickers for matching
        known = set()
        try:
            result = self.session.execute(text(
                "SELECT ticker FROM instruments WHERE is_active = TRUE AND is_delisted = FALSE"
            ))
            known = {r[0] for r in result.fetchall()}
        except Exception:
            pass

        count = 0
        for item in items:
            # Extract tickers
            full_text = f"{item.title} {item.description}"
            item.tickers = self.extract_tickers(full_text, known)

            # Score sentiment
            score, label = self.score_sentiment(full_text)

            # Determine date
            item_date = item.published.date() if hasattr(item.published, "date") else date.today()

            # Store with ticker association (or NULL if no ticker found)
            tickers_to_store = item.tickers if item.tickers else [None]
            for ticker in tickers_to_store:
                try:
                    self.session.execute(text("""
                        INSERT INTO news_sentiment (ticker, date, headline, sentiment_score, sentiment_label, source, url)
                        VALUES (:ticker, :date, :headline, :score, :label, :source, :url)
                        ON CONFLICT DO NOTHING
                    """), {
                        "ticker": ticker,
                        "date": item_date,
                        "headline": item.title[:500],
                        "score": score,
                        "label": label,
                        "source": item.source,
                        "url": item.url,
                    })
                    count += 1
                except Exception as e:
                    logger.debug("Store error for %s: %s", item.url, e)

        self.session.commit()
        logger.info("Stored %d news_sentiment rows", count)
        return count

    @staticmethod
    def _get_text(element, tag: str) -> str:
        el = element.find(tag)
        return el.text.strip() if el is not None and el.text else ""

    @staticmethod
    def _get_text_ns(element, tag: str, ns: dict) -> str:
        el = element.find(tag, ns)
        return el.text.strip() if el is not None and el.text else ""

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Parse various date formats from RSS feeds."""
        if not date_str:
            return None
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        return None
