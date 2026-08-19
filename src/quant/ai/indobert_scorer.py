"""IndoBERT sentiment scorer for news headlines.

Uses indobenchmark/indobert-base-p1 (or fallback to multilingual model)
to re-score news_sentiment rows with proper NLP instead of keyword matching.

GPU: Runs on cuda:1 (secondary GPU) to leave cuda:0 free for DL training.
"""

from __future__ import annotations

import logging
from typing import Optional

import torch
from sqlalchemy import text

from quant.core.db import get_db

logger = logging.getLogger(__name__)

__all__ = ["IndoBERTScorer", "score_existing_news"]


class IndoBERTScorer:
    """IndoBERT-based sentiment scorer for Indonesian financial news.

    Usage::

        scorer = IndoBERTScorer()
        score = scorer.score("Saham BBCA naik tajam hari ini")
        # → (0.85, "positive")

        # Batch score existing news_sentiment rows
        scorer.score_database(limit=1000)
    """

    def __init__(
        self,
        model_name: str = "indobenchmark/indobert-base-p1",
        device: str = "cuda:1",
        batch_size: int = 32,
    ):
        self.model_name = model_name
        self.device = device if torch.cuda.is_available() else "cpu"
        self.batch_size = batch_size
        self._pipeline = None
        self._session = None

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
        return self._session

    @property
    def pipeline(self):
        """Lazy-load the sentiment analysis pipeline."""
        if self._pipeline is None:
            from transformers import pipeline

            logger.info("Loading %s on %s...", self.model_name, self.device)
            try:
                self._pipeline = pipeline(
                    "sentiment-analysis",
                    model=self.model_name,
                    device=self.device,
                    batch_size=self.batch_size,
                    truncation=True,
                    max_length=512,
                )
                logger.info("Loaded %s successfully", self.model_name)
            except Exception as e:
                logger.warning(
                    "Failed to load %s: %s. Falling back to tabularisai/multilingual-sentiment-analysis",
                    self.model_name, e,
                )
                self._pipeline = pipeline(
                    "sentiment-analysis",
                    model="tabularisai/multilingual-sentiment-analysis",
                    device=self.device,
                    batch_size=self.batch_size,
                    truncation=True,
                    max_length=512,
                )
                logger.info("Loaded fallback multilingual model")
        return self._pipeline

    def score(self, text: str) -> tuple[float, str]:
        """Score a single text.

        Returns:
            (score, label) where score is in [-1, 1] and
            label is 'positive', 'negative', or 'neutral'.
        """
        result = self.pipeline(text[:512])
        label = result[0]["label"].lower()
        raw_score = result[0]["score"]

        # Normalize to [-1, 1] range
        if "pos" in label:
            return raw_score, "positive"
        elif "neg" in label:
            return -raw_score, "negative"
        else:
            return 0.0, "neutral"

    def score_batch(self, texts: list[str]) -> list[tuple[float, str]]:
        """Score a batch of texts."""
        truncated = [t[:512] for t in texts]
        results = self.pipeline(truncated)
        scored = []
        for r in results:
            label = r["label"].lower()
            raw_score = r["score"]
            if "pos" in label:
                scored.append((raw_score, "positive"))
            elif "neg" in label:
                scored.append((-raw_score, "negative"))
            else:
                scored.append((0.0, "neutral"))
        return scored

    def score_database(self, limit: int = 1000, re_score: bool = True) -> int:
        """Re-score existing news_sentiment rows with IndoBERT.

        Args:
            limit: Maximum rows to score
            re_score: If True, re-score all rows. If False, only score rows
                      with NULL sentiment_score.

        Returns:
            Number of rows updated.
        """
        query = "SELECT id, headline FROM news_sentiment"
        if not re_score:
            query += " WHERE sentiment_score IS NULL"
        query += " ORDER BY date DESC LIMIT :limit"

        rows = self.session.execute(text(query), {"limit": limit}).fetchall()
        if not rows:
            logger.info("No news_sentiment rows to score")
            return 0

        logger.info("Scoring %d headlines with IndoBERT...", len(rows))
        ids = [r[0] for r in rows]
        headlines = [r[1] or "" for r in rows]

        updated = 0
        for i in range(0, len(headlines), self.batch_size):
            batch_texts = headlines[i : i + self.batch_size]
            batch_ids = ids[i : i + self.batch_size]

            try:
                scores = self.score_batch(batch_texts)
                for row_id, (score, label) in zip(batch_ids, scores):
                    self.session.execute(text(
                        "UPDATE news_sentiment "
                        "SET sentiment_score = :score, sentiment_label = :label "
                        "WHERE id = :id"
                    ), {"score": score, "label": label, "id": row_id})
                    updated += 1
            except Exception as e:
                logger.warning("Batch %d failed: %s", i // self.batch_size, e)

            self.session.commit()
            if (i // self.batch_size + 1) % 10 == 0:
                logger.info("  Scored %d/%d", i + len(batch_texts), len(headlines))

        logger.info("Updated %d news_sentiment rows with IndoBERT scores", updated)
        return updated

    def close(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass


def score_existing_news(limit: int = 1000, re_score: bool = True) -> int:
    """Convenience function to score existing news with IndoBERT."""
    scorer = IndoBERTScorer()
    try:
        return scorer.score_database(limit=limit, re_score=re_score)
    finally:
        scorer.close()
