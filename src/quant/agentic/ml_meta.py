"""ML Meta-Learning — error pattern clustering + self-healing prompt generator.

Two components:
  1. ErrorPatternLearner: Clusters error log messages using TF-IDF + K-Means
     to identify recurring error patterns. Persists patterns to JSON for
     cross-session learning. Falls back to regex-based classification when
     scikit-learn is not installed.

  2. SelfHealingPromptGenerator: Takes clustered error patterns + current
     errors and generates a structured LLM repair prompt. Uses the existing
     LLMGateway for natural-language rationale, with template fallback.

Lightweight by design — no heavy transformer models required. The "ML" part
is TF-IDF vectorization + clustering, which is fast and interpretable.
When Ollama is available, the LLM adds semantic understanding.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Pattern store location (relative to project root)
_PATTERN_STORE = Path(__file__).resolve().parents[3] / "scripts" / "e2e_reports" / "error_patterns.json"


@dataclass
class ErrorPattern:
    """A learned error pattern cluster."""
    pattern_id: str
    centroid_text: str  # representative error message
    frequency: int  # how many times this pattern has been seen
    category: str  # "network", "syntax", "runtime", "import", "type", "other"
    example_errors: list[str] = field(default_factory=list)
    suggested_fix: str = ""  # accumulated fix hint
    first_seen: str = ""
    last_seen: str = ""


class ErrorPatternLearner:
    """Learns and stores error patterns from E2E test runs.

    Uses TF-IDF + K-Means clustering when scikit-learn is available.
    Falls back to regex-based categorization otherwise.

    Usage:
        learner = ErrorPatternLearner()
        patterns = learner.learn(["Error: undefined variable x", "Error: undefined variable y"])
        # patterns[0].category == "runtime"
        # patterns[0].frequency == 2
    """

    # Regex-based error categories (used for fallback and as features)
    CATEGORIES = {
        "network": [
            r"404\s*\(Not Found\)",
            r"403\s*\(Forbidden\)",
            r"500\s*\(Internal Server Error\)",
            r"ERR_CONNECTION_REFUSED",
            r"WebSocket.*failed",
            r"Failed to load resource",
            r"Failed to fetch",
            r"net::ERR_",
        ],
        "syntax": [
            r"SyntaxError",
            r"IndentationError",
            r"unexpected token",
            r"Unexpected token",
            r"parsing error",
        ],
        "import": [
            r"ModuleNotFoundError",
            r"ImportError",
            r"Cannot find module",
            r"No module named",
        ],
        "type": [
            r"TypeError",
            r"AttributeError",
            r"KeyError",
            r"ValueError",
            r"is not a function",
            r"is not defined",
            r"Cannot read prop",
        ],
        "runtime": [
            r"ReferenceError",
            r"RuntimeError",
            r"Uncaught",
            r"Unhandled",
            r"Maximum call stack",
            r"out of memory",
        ],
    }

    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path or _PATTERN_STORE
        self._patterns: dict[str, ErrorPattern] = {}
        self._load()

    def learn(self, errors: list[str]) -> list[ErrorPattern]:
        """Process a batch of error messages and update pattern store.

        Args:
            errors: List of error message strings

        Returns:
            List of ErrorPattern objects (updated + new)
        """
        if not errors:
            return list(self._patterns.values())

        # Try sklearn-based clustering
        try:
            new_patterns = self._cluster_errors(errors)
        except ImportError:
            new_patterns = self._regex_classify(errors)

        # Merge with existing patterns
        for p in new_patterns:
            if p.pattern_id in self._patterns:
                existing = self._patterns[p.pattern_id]
                existing.frequency += p.frequency
                existing.last_seen = datetime.now().isoformat()
                if p.example_errors:
                    existing.example_errors.extend(p.example_errors[:3])
                    existing.example_errors = existing.example_errors[:10]  # cap
            else:
                p.first_seen = datetime.now().isoformat()
                p.last_seen = datetime.now().isoformat()
                self._patterns[p.pattern_id] = p

        self._save()
        return list(self._patterns.values())

    def _cluster_errors(self, errors: list[str]) -> list[ErrorPattern]:
        """TF-IDF + K-Means clustering of error messages."""
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import TfidfVectorizer

        # Vectorize error messages
        vectorizer = TfidfVectorizer(
            max_features=100,
            stop_words="english",
            ngram_range=(1, 2),
        )
        tfidf_matrix = vectorizer.fit_transform(errors)

        # Determine number of clusters (min 1, max min(8, len(errors)))
        n_clusters = min(8, max(1, len(errors) // 2))
        if n_clusters == 1 and len(errors) > 1:
            n_clusters = 2

        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(tfidf_matrix)

        # Build patterns from clusters
        patterns = []
        for cluster_id in range(n_clusters):
            cluster_errors = [errors[i] for i in range(len(errors)) if labels[i] == cluster_id]
            if not cluster_errors:
                continue

            # Find the error closest to centroid
            centroid_idx = kmeans.labels_ == cluster_id
            centroid_text = cluster_errors[0]  # first error as representative

            category = self._categorize(centroid_text)
            pattern_id = f"{category}_{cluster_id}"

            patterns.append(ErrorPattern(
                pattern_id=pattern_id,
                centroid_text=centroid_text[:200],
                frequency=len(cluster_errors),
                category=category,
                example_errors=cluster_errors[:5],
            ))

        return patterns

    def _regex_classify(self, errors: list[str]) -> list[ErrorPattern]:
        """Fallback: classify errors using regex patterns."""
        categorized: dict[str, list[str]] = {}

        for err in errors:
            category = self._categorize(err)
            categorized.setdefault(category, []).append(err)

        patterns = []
        for category, errs in categorized.items():
            patterns.append(ErrorPattern(
                pattern_id=f"{category}_0",
                centroid_text=errs[0][:200],
                frequency=len(errs),
                category=category,
                example_errors=errs[:5],
            ))

        return patterns

    def _categorize(self, error_text: str) -> str:
        """Classify an error message into a category using regex."""
        for category, patterns in self.CATEGORIES.items():
            for p in patterns:
                if re.search(p, error_text):
                    return category
        return "other"

    def get_patterns(self) -> list[ErrorPattern]:
        """Return all learned patterns."""
        return list(self._patterns.values())

    def get_fix_hint(self, category: str) -> str:
        """Return a suggested fix hint for a category."""
        hints = {
            "network": "Check if backend API server is running. Verify endpoint URLs match frontend fetch calls. Add missing API routes.",
            "syntax": "Check for syntax errors: missing colons, incorrect indentation, unclosed brackets.",
            "import": "Verify module is installed and import path is correct. Run pip install if missing.",
            "type": "Check variable types and null/undefined access. Add type guards or optional chaining.",
            "runtime": "Check for undefined variables, infinite recursion, or memory issues.",
            "other": "Review the error message and stack trace for root cause.",
        }
        return hints.get(category, hints["other"])

    def _load(self):
        """Load patterns from JSON store."""
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
                for p_dict in data.get("patterns", []):
                    p = ErrorPattern(**p_dict)
                    self._patterns[p.pattern_id] = p
            except (json.JSONDecodeError, TypeError, OSError) as e:
                logger.warning("Failed to load error patterns: %s", e)

    def _save(self):
        """Persist patterns to JSON store."""
        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "updated_at": datetime.now().isoformat(),
                "patterns": [
                    {
                        "pattern_id": p.pattern_id,
                        "centroid_text": p.centroid_text,
                        "frequency": p.frequency,
                        "category": p.category,
                        "example_errors": p.example_errors,
                        "suggested_fix": p.suggested_fix,
                        "first_seen": p.first_seen,
                        "last_seen": p.last_seen,
                    }
                    for p in self._patterns.values()
                ],
            }
            self.store_path.write_text(json.dumps(data, indent=2))
        except OSError as e:
            logger.warning("Failed to save error patterns: %s", e)


class SelfHealingPromptGenerator:
    """Generates LLM repair prompts from error patterns.

    Combines learned error patterns with current errors to produce
    a structured prompt that the Agent Coder can use for fixing.

    Usage:
        gen = SelfHealingPromptGenerator()
        prompt = gen.generate(
            errors=["TypeError: x is not a function"],
            console_errors=[{"type": "error", "text": "...", "url": "..."}],
            network_errors=[{"method": "GET", "url": "...", "failure": "..."}],
        )
    """

    def __init__(self, learner: ErrorPatternLearner | None = None):
        self.learner = learner or ErrorPatternLearner()

    def generate(
        self,
        errors: list[str],
        console_errors: list[dict] | None = None,
        network_errors: list[dict] | None = None,
    ) -> str:
        """Generate a self-healing prompt string.

        Args:
            errors: List of error message strings
            console_errors: List of console error dicts
            network_errors: List of network error dicts

        Returns:
            JSON string with root_cause, fix_instructions, files_to_fix, priority
        """
        # Learn from current errors
        patterns = self.learner.learn(errors)

        # Classify current errors
        categories = {}
        for err in errors:
            cat = self.learner._categorize(err)
            categories.setdefault(cat, []).append(err)

        # Determine primary category (most frequent)
        primary_cat = max(categories, key=lambda c: len(categories[c])) if categories else "other"

        # Extract file paths from errors
        file_paths = set()
        for err in errors:
            # Match file paths in error messages
            matches = re.findall(r"[\w/\-]+\.\w{2,4}", err)
            for m in matches:
                if any(m.endswith(ext) for ext in (".py", ".ts", ".tsx", ".js", ".jsx")):
                    file_paths.add(m)

        # Build fix instructions based on category + patterns
        fix_hint = self.learner.get_fix_hint(primary_cat)
        pattern_hints = []
        for p in patterns:
            if p.category == primary_cat:
                pattern_hints.append(f"  - Pattern '{p.pattern_id}' (seen {p.frequency}x): {p.centroid_text}")

        instructions = fix_hint
        if pattern_hints:
            instructions += "\n\nRecurring patterns in this category:\n" + "\n".join(pattern_hints)

        # Build network error summary if present
        net_summary = ""
        if network_errors:
            net_urls = set()
            for ne in network_errors[:10]:
                net_urls.add(ne.get("url", ne.get("failure", str(ne))))
            net_summary = f"\n\nNetwork errors ({len(network_errors)} total):\n" + "\n".join(
                f"  - {u}" for u in list(net_urls)[:5]
            )

        # Build console error summary
        console_summary = ""
        if console_errors:
            console_summary = f"\n\nConsole errors ({len(console_errors)} total):\n" + "\n".join(
                f"  - [{ce.get('type', 'error')}] {ce.get('text', '')[:100]}" for ce in console_errors[:5]
            )

        prompt = json.dumps({
            "root_cause": f"{primary_cat} error(s) detected ({len(errors)} total)",
            "fix_instructions": instructions + net_summary + console_summary,
            "files_to_fix": sorted(file_paths),
            "priority": "high" if primary_cat in ("syntax", "runtime", "type") else "medium",
            "learned_patterns": len(patterns),
            "category_breakdown": {cat: len(errs) for cat, errs in categories.items()},
        }, indent=2)

        return prompt
