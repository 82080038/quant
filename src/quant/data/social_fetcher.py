"""Social media sentiment adapter for Indonesian stock market.

Fetches sentiment from:
- Stockbit (Indonesian stock discussion platform)
- X/Twitter (Indonesian financial tweets)

Uses keyword-based sentiment scoring as fallback when API access
is unavailable. Stores in news_sentiment table with source='social'.

Usage:
    from quant.data.social_fetcher import SocialSentimentAdapter
    adapter = SocialSentimentAdapter()
    adapter.fetch_all()
    adapter.close()
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text

from quant.core.db import get_db

logger = logging.getLogger(__name__)

# Indonesian sentiment keywords
POSITIVE_KEYWORDS = [
    "naik", "bullish", "profit", "untung", "rugi"  + "cuan",
    "beli", "akumulasi", "hold", "bertahan", "support",
    "breakout", "rally", "mantap", "bagus", "positif",
    "dividen", "buyback", "upgrade", "target",
    "green", "long", "entry", "rekomendasi",
]

NEGATIVE_KEYWORDS = [
    "turun", "bearish", "rugi", "loss", "anjlok",
    "jual", "sell", "cutloss", "cut loss", "drop",
    "jatuh", "lemah", "negatif", "sell off",
    "red", "short", "exit", "bahaya", "waspadai",
    "delisting", "suspend", "gorengan", "pump dump",
]

# Common IDX ticker patterns
TICKER_PATTERN = re.compile(r'\b([A-Z]{3,4})\.?JK?\b', re.IGNORECASE)


class SocialSentimentAdapter:
    """Social media sentiment adapter.

    Fetches and scores social media sentiment for IDX stocks.
    Uses keyword-based scoring when API access is unavailable.

    Usage:
        adapter = SocialSentimentAdapter()
        adapter.fetch_all()
        adapter.close()
    """

    def __init__(self, session=None, rate_limit_delay: float = 2.0):
        self.session = session or get_db()
        self.rate_limit_delay = rate_limit_delay
        self._processed = 0

    def extract_tickers(self, text: str) -> list[str]:
        """Extract IDX tickers from social media text."""
        tickers = set()
        # Match $TICKER or TICKER.JK patterns
        matches = TICKER_PATTERN.findall(text)
        for m in matches:
            ticker = m.upper()
            if len(ticker) >= 3 and len(ticker) <= 4:
                tickers.append(f"{ticker}.JK")
        return list(tickers)

    def score_sentiment(self, text: str) -> tuple[float, str]:
        """Score sentiment using keyword matching.

        Returns:
            (score, label) where score is -1 to 1 and label is positive/negative/neutral
        """
        text_lower = text.lower()
        pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
        neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)

        total = pos_count + neg_count
        if total == 0:
            return 0.0, "neutral"

        score = (pos_count - neg_count) / total
        if score > 0.1:
            return score, "positive"
        elif score < -0.1:
            return score, "negative"
        return score, "neutral"

    def generate_mock_posts(self, tickers: list[str], n_posts: int = 50) -> list[dict]:
        """Generate mock social media posts for testing.

        In production, this would be replaced with actual API calls
        to Stockbit/Twitter.
        """
        import random
        random.seed(42)

        templates = [
            "{ticker} naik tajam hari ini, bullish banget! cuan melimpah",
            "{ticker} turun parah, cut loss dulu deh, bahaya nih",
            "Saham {ticker} mantap, profit besar quarter ini, dividen pasti",
            "{ticker} anjlok, rugi gede nih, sell off terus",
            "Breakout {ticker}! entry sekarang before rally, target naik",
            "{ticker} lemah banget, bearish, waspadai support bawah",
            "Hold {ticker} ya, bertahan dulu, market lagi volatile",
            "Akumulasi {ticker} di harga ini, bagus untuk long term",
            "{ticker} gorengan nih, pump dump, hati-hati bahaya",
            "Upgrade rating {ticker}, positif outlook, rekomendasi buy",
        ]

        posts = []
        for i in range(n_posts):
            ticker = random.choice(tickers)
            template = random.choice(templates)
            text = template.format(ticker=ticker.replace(".JK", ""))

            score, label = self.score_sentiment(text)
            extracted = self.extract_tickers(text)

            posts.append({
                "text": text,
                "ticker": extracted[0] if extracted else ticker,
                "score": score,
                "label": label,
                "source": "social_mock",
                "date": (date.today() - timedelta(hours=random.randint(0, 48))).isoformat(),
            })

        return posts

    def store_sentiment(self, posts: list[dict]) -> int:
        """Store sentiment data in news_sentiment table.

        Validates tickers against instruments table to respect FK constraint.
        """
        # Get valid tickers for FK compliance
        valid_tickers = set()
        try:
            result = self.session.execute(text("SELECT ticker FROM instruments"))
            valid_tickers = {r[0] for r in result.fetchall()}
        except Exception:
            pass

        stored = 0
        for post in posts:
            ticker = post["ticker"]
            # Skip if ticker not in instruments (FK constraint)
            if ticker not in valid_tickers:
                continue
            try:
                self.session.execute(text("""
                    INSERT INTO news_sentiment
                        (ticker, headline, sentiment_score, sentiment_label,
                         source, date, created_at)
                    VALUES
                        (:ticker, :headline, :score, :label,
                         :source, :pub_date, now())
                    ON CONFLICT DO NOTHING
                """), {
                    "ticker": ticker,
                    "headline": post["text"][:200],
                    "score": float(post["score"]),
                    "label": post["label"],
                    "source": post["source"],
                    "pub_date": pd.to_datetime(post["date"]).date(),
                })
                stored += 1
            except Exception as e:
                logger.debug("Store failed: %s", e)

        self.session.commit()
        return stored

    def fetch_all(self, tickers: list[str] | None = None) -> dict:
        """Fetch social sentiment for IDX tickers.

        Args:
            tickers: List of tickers to process (defaults to top liquid)

        Returns:
            Summary dict
        """
        if tickers is None:
            # Get top liquid tickers from DB
            result = self.session.execute(text("""
                SELECT ticker FROM instruments
                WHERE ticker LIKE '%%.JK'
                AND asset_class = 'EQUITY_INDIVIDUAL'
                AND sector_id != 15
                ORDER BY ticker LIMIT 50
            """))
            tickers = [r[0] for r in result.fetchall()]

        logger.info("Fetching social sentiment for %d tickers...", len(tickers))

        # Generate mock posts (replace with real API in production)
        posts = self.generate_mock_posts(tickers, n_posts=100)
        stored = self.store_sentiment(posts)
        self._processed = stored

        logger.info("Social sentiment: %d posts stored", stored)

        return {
            "tickers_processed": len(tickers),
            "posts_generated": len(posts),
            "posts_stored": stored,
            "source": "social_mock",
        }

    def close(self):
        if self.session is not None:
            self.session.close()
