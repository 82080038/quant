"""Sentiment Engine (pustaka/18 §5).

Combines 6 sentiment sources with weighted aggregation:
    Foreign Flow:       0.25
    Broker Summary:     0.20
    Historical:         0.20
    Social Media:       0.15
    Google Trends:      0.10
    News NLP:           0.10

Weights are renormalized based on available sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field

INDONESIAN_POSITIVE_WORDS: frozenset[str] = frozenset(
    {
        "naik", "untung", "bullish", "beli", "tumbuh", "optimis", "rally",
        "profit", "dividen", "rekomendasi", "akumulasi", "positif", "gain",
        "surplus", "ekspansi", "naiknya", "melonjak", "menguat", "meroket",
        "mendapatkan", "mencatatkan", "meningkat", "peluang", "mendapat",
        "membeli", "rebound", "pulih", "premi", "capai", "tembus",
        "support", "hold", "outperform", "overweight", "target",
        "upgrade", "potensial", "menarik", "solid", "stabil",
    },
)

INDONESIAN_NEGATIVE_WORDS: frozenset[str] = frozenset(
    {
        "turun", "rugi", "bearish", "jual", "lemah", "jatuh", "anjlok",
        "crash", "fraud", "distribusi", "negatif", "loss", "defisit",
        "terjun", "melemah", "terpuruk", "penurunan", "tekanan",
        "korban", "gagal", "terendah", "pelarian", "cut", "sell",
        "underperform", "underweight", "downgrade", "risiko",
        "anjur", "blokir", "suspend", "delisting",
        "perampasan", "sita", "investigasi", "pemeriksaan",
    },
)

NEGATION_WORDS: frozenset[str] = frozenset(
    {"tidak", "bukan", "jangan", "tak", "nggak"},
)

SENTIMENT_WEIGHTS: dict[str, float] = {
    "foreign_flow": 0.25,
    "broker_summary": 0.20,
    "historical": 0.20,
    "social_media": 0.15,
    "google_trends": 0.10,
    "news_nlp": 0.10,
}


@dataclass
class SentimentScore:
    """Sentiment analysis result."""

    ticker: str
    score: float
    label: str
    sources: dict[str, float] = field(default_factory=dict)
    breakdown: dict[str, float] = field(default_factory=dict)


class SentimentEngine:
    """Sentiment engine aggregating multiple sentiment sources."""

    def analyze(
        self,
        ticker: str,
        foreign_flow_score: float | None = None,
        broker_summary_score: float | None = None,
        historical_score: float | None = None,
        social_media_score: float | None = None,
        google_trends_score: float | None = None,
        news_texts: list[str] | None = None,
    ) -> SentimentScore:
        """Analyze sentiment from available sources.

        Args:
            ticker: Stock ticker.
            foreign_flow_score: Pre-computed foreign flow score (0-100).
            broker_summary_score: Smart money broker score (0-100).
            historical_score: Historical sentiment score (0-100).
            social_media_score: Social media sentiment score (0-100).
            google_trends_score: Google Trends score (0-100).
            news_texts: List of news headlines for NLP analysis.

        Returns:
            SentimentScore with aggregated score and per-source breakdown.
        """
        sources: dict[str, float] = {}
        breakdown: dict[str, float] = {}

        if foreign_flow_score is not None:
            sources["foreign_flow"] = foreign_flow_score
        if broker_summary_score is not None:
            sources["broker_summary"] = broker_summary_score
        if historical_score is not None:
            sources["historical"] = historical_score
        if social_media_score is not None:
            sources["social_media"] = social_media_score
        if google_trends_score is not None:
            sources["google_trends"] = google_trends_score

        if news_texts is not None:
            news_score = self._analyze_news(news_texts)
            sources["news_nlp"] = news_score

        if not sources:
            return SentimentScore(
                ticker=ticker,
                score=50.0,
                label="neutral",
                sources={},
                breakdown={},
            )

        # Renormalize weights for available sources
        total_weight = sum(
            SENTIMENT_WEIGHTS.get(src, 0) for src in sources
        )
        if total_weight == 0:
            total_weight = 1.0

        weighted_sum = 0.0
        for src, score in sources.items():
            weight = SENTIMENT_WEIGHTS.get(src, 0) / total_weight
            weighted_sum += score * weight
            breakdown[src] = round(score * weight, 2)

        final_score = min(100.0, max(0.0, weighted_sum))

        if final_score >= 70:
            label = "positive"
        elif final_score >= 40:
            label = "neutral"
        else:
            label = "negative"

        return SentimentScore(
            ticker=ticker,
            score=round(final_score, 2),
            label=label,
            sources=sources,
            breakdown=breakdown,
        )

    def _analyze_news(self, texts: list[str]) -> float:
        """Analyze news texts using unified NewsSentimentAnalyzer.

        Delegates to market.analysis.news_sentiment for consistent scoring.
        Score is converted to 0-100 scale (50 = neutral).

        Args:
            texts: List of news headlines or text snippets.

        Returns:
            Sentiment score 0-100 (50 = neutral).
        """
        from quant.analysis.news_sentiment import analyze_news_texts

        return analyze_news_texts(texts)
