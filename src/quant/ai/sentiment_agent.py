"""Sentiment Analyst Agent — IndoBERT-based Indonesian financial NLP.

Uses IndoBERT (or FinBERT for English) to analyze news sentiment
for IDX stocks. Provides sentiment signals that feed into the
SignalAggregator.

The agent:
  1. Fetches recent news from RSS feeds / DB
  2. Runs IndoBERT sentiment classification
  3. Aggregates per-ticker sentiment scores
  4. Computes sentiment momentum and news volume features
  5. Outputs SignalResult compatible with aggregator

IDX-specific findings:
  - Sentiment-price correlation: 0.26 individual → 0.43 co-occurrence
  - 60% teknikal / 40% sentimen optimal weight
  - Banking & Mining most sentiment-sensitive
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from quant.signals.aggregator import SignalResult

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """A single news item with sentiment."""
    date: date
    ticker: Optional[str]
    headline: str
    sentiment_score: float  # [-1, 1]
    sentiment_label: str    # positive / negative / neutral
    source: str
    url: str = ""


@dataclass
class SentimentSummary:
    """Aggregated sentiment for a ticker."""
    ticker: str
    avg_sentiment: float
    sentiment_momentum: float
    news_count: int
    positive_pct: float
    negative_pct: float
    signal_value: float  # [-1, 1] for aggregator
    confidence: float


class SentimentAnalystAgent:
    """IndoBERT-based sentiment analysis agent.

    Usage:
        agent = SentimentAnalystAgent()
        signals = agent.generate_signals(
            tickers=["BBCA.JK", "BBRI.JK"],
            as_of_date=date(2024, 6, 1),
        )
        for sig in signals:
            print(f"{sig.ticker}: {sig.signal_value:.4f}")
    """

    # Sentiment signal weight in composite (40% sentimen per IDX research)
    SENTIMENT_WEIGHT = 0.40

    def __init__(
        self,
        model_name: str = "indobenchmark/indobert-large-p1",
        use_finbert_for_english: bool = True,
        device: str = "auto",
        session=None,
    ):
        self.model_name = model_name
        self.use_finbert_for_english = use_finbert_for_english
        self.device = device
        self._session = session
        self._tokenizer = None
        self._model = None
        self._is_loaded = False

    def _load_model(self):
        """Load IndoBERT model (lazy loading)."""
        if self._is_loaded:
            return

        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForSequenceClassification

            device = self.device
            if device == "auto":
                device = "cuda:0" if torch.cuda.is_available() else "cpu"

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            self._model.to(device)
            self._model.eval()
            self.device = device
            self._is_loaded = True
            logger.info("IndoBERT loaded on %s", device)
        except Exception as e:
            logger.warning("Failed to load IndoBERT: %s. Using fallback.", e)
            self._is_loaded = False

    def classify_sentiment(self, text: str) -> tuple[float, str]:
        """Classify sentiment of a text string.

        Args:
            text: News headline or article text

        Returns:
            (sentiment_score, label) — score in [-1, 1], label in {positive, negative, neutral}
        """
        self._load_model()

        if not self._is_loaded:
            return self._fallback_sentiment(text)

        try:
            import torch

            inputs = self._tokenizer(
                text, return_tensors="pt", truncation=True,
                max_length=512, padding=True,
            ).to(self.device)

            with torch.no_grad():
                outputs = self._model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1)
                pred = torch.argmax(probs, dim=-1).item()
                confidence = float(probs[0][pred].item())

            # Map to [-1, 1] — assumes 3-class model: negative(0), neutral(1), positive(2)
            label_map = {0: ("negative", -1.0), 1: ("neutral", 0.0), 2: ("positive", 1.0)}
            label, score = label_map.get(pred, ("neutral", 0.0))
            score *= confidence

            return score, label
        except Exception as e:
            logger.warning("Sentiment classification failed: %s", e)
            return self._fallback_sentiment(text)

    @staticmethod
    def _fallback_sentiment(text: str) -> tuple[float, str]:
        """Simple keyword-based fallback sentiment.

        Used when IndoBERT is not available.
        """
        positive_words = ["naik", "untung", "positif", "tumbuh", "rug", "beli", "bullish",
                          "gain", "surplus", "dividen", "akuisisi", "ekspansi"]
        negative_words = ["turun", "rugi", "negatif", "turun", "jual", "bearish", "loss",
                          "defisit", "gagal", "bangkrut", "penurunan", "anjlok", "korupsi"]

        text_lower = text.lower()
        pos_count = sum(1 for w in positive_words if w in text_lower)
        neg_count = sum(1 for w in negative_words if w in text_lower)

        if pos_count > neg_count:
            return min(1.0, 0.5 + 0.1 * (pos_count - neg_count)), "positive"
        elif neg_count > pos_count:
            return max(-1.0, -(0.5 + 0.1 * (neg_count - pos_count))), "negative"
        else:
            return 0.0, "neutral"

    def generate_signals(
        self,
        tickers: list[str],
        as_of_date: date,
        lookback_days: int = 7,
    ) -> list[SignalResult]:
        """Generate sentiment signals for tickers.

        Args:
            tickers: Tickers to analyze
            as_of_date: Decision date
            lookback_days: How many days of news to consider

        Returns:
            List of SignalResult for each ticker
        """
        signals = []

        for ticker in tickers:
            summary = self._analyze_ticker(ticker, as_of_date, lookback_days)
            if summary is None:
                continue

            direction = "long" if summary.signal_value > 0.1 else "short" if summary.signal_value < -0.1 else "neutral"

            signals.append(SignalResult(
                engine_name="sentiment",
                ticker=ticker,
                signal_value=summary.signal_value,
                confidence=summary.confidence,
                direction=direction,
                rationale=f"Sentiment: {summary.avg_sentiment:.3f}, momentum: {summary.sentiment_momentum:.3f}, news: {summary.news_count}",
                weight=self.SENTIMENT_WEIGHT,
            ))

        return signals

    def _analyze_ticker(
        self,
        ticker: str,
        as_of_date: date,
        lookback_days: int,
    ) -> Optional[SentimentSummary]:
        """Analyze sentiment for a single ticker."""
        news_items = self._fetch_news(ticker, as_of_date, lookback_days)
        if not news_items:
            return None

        scores = [n.sentiment_score for n in news_items]
        avg_sentiment = float(np.mean(scores))
        positive = sum(1 for s in scores if s > 0.1) / len(scores)
        negative = sum(1 for s in scores if s < -0.1) / len(scores)

        # Sentiment momentum: recent vs older news
        mid = len(news_items) // 2
        recent = np.mean(scores[:mid]) if mid > 0 else scores[0]
        older = np.mean(scores[mid:]) if mid < len(scores) else 0
        momentum = float(recent - older)

        # Signal: weighted combination of level and momentum
        signal_value = 0.6 * avg_sentiment + 0.4 * momentum
        signal_value = float(np.clip(signal_value, -1, 1))

        # Confidence: based on news volume and agreement
        agreement = max(positive, negative) if max(positive, negative) > 0 else 0.5
        volume_factor = min(1.0, len(news_items) / 10)
        confidence = float(agreement * volume_factor)

        return SentimentSummary(
            ticker=ticker,
            avg_sentiment=avg_sentiment,
            sentiment_momentum=momentum,
            news_count=len(news_items),
            positive_pct=positive,
            negative_pct=negative,
            signal_value=signal_value,
            confidence=confidence,
        )

    def _fetch_news(
        self,
        ticker: str,
        as_of_date: date,
        lookback_days: int,
    ) -> list[NewsItem]:
        """Fetch news from DB or RSS feeds.

        Falls back to DB query if available, otherwise returns empty.
        """
        if self._session is None:
            return []

        try:
            from sqlalchemy import text

            start = as_of_date - timedelta(days=lookback_days)
            result = self._session.execute(text("""
                SELECT date, headline, sentiment_score, sentiment_label, source, url
                FROM news_sentiment
                WHERE (ticker = :ticker OR ticker IS NULL)
                  AND date BETWEEN :start AND :end
                ORDER BY date DESC
                LIMIT 50
            """), {"ticker": ticker, "start": start, "end": as_of_date})

            items = []
            for row in result.fetchall():
                items.append(NewsItem(
                    date=row[0],
                    ticker=ticker,
                    headline=row[1],
                    sentiment_score=float(row[2]) if row[2] else 0.0,
                    sentiment_label=row[3] or "neutral",
                    source=row[4] or "",
                    url=row[5] or "",
                ))
            return items
        except Exception as e:
            logger.warning("News fetch failed for %s: %s", ticker, e)
            return []
