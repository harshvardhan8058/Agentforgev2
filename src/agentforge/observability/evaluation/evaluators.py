"""Deterministic evaluators: ``Exact_Match``, ``Contains``, ``Heuristic`` (Req 6.3, 6.7).

Each ``score(*, input, expected, actual) -> float`` is a pure function of its inputs, so
repeated runs over the same ``(input, expected, actual)`` yield identical scores on the
keyless path (Req 6.3, 6.6).
"""

from __future__ import annotations

from agentforge.observability.evaluation.base import Evaluator


class Exact_Match_Evaluator(Evaluator):
    """1.0 iff ``actual`` exactly equals ``expected``, else 0.0."""

    @property
    def name(self) -> str:
        return "exact_match"

    def score(self, *, input: str, expected: str | None, actual: str) -> float:
        """Return 1.0 iff ``actual == expected`` (a missing ``expected`` scores 0.0)."""
        if expected is None:
            return 0.0
        return 1.0 if actual == expected else 0.0


class Contains_Evaluator(Evaluator):
    """1.0 iff ``expected`` is a substring of ``actual``, else 0.0."""

    @property
    def name(self) -> str:
        return "contains"

    def score(self, *, input: str, expected: str | None, actual: str) -> float:
        """Return 1.0 iff ``expected`` occurs within ``actual`` (missing -> 0.0)."""
        if expected is None:
            return 0.0
        return 1.0 if expected in actual else 0.0


class Heuristic_Evaluator(Evaluator):
    """A deterministic token-overlap (Jaccard) similarity scorer in ``[0.0, 1.0]``."""

    @property
    def name(self) -> str:
        return "heuristic"

    def score(self, *, input: str, expected: str | None, actual: str) -> float:
        """Return the Jaccard similarity of the whitespace tokens of expected/actual.

        A pure function of ``(expected, actual)``: two empty token sets are perfectly
        similar (1.0); a missing ``expected`` behaves like an empty expected set.
        """
        if expected is None:
            expected = ""
        expected_tokens = set(expected.split())
        actual_tokens = set(actual.split())
        if not expected_tokens and not actual_tokens:
            return 1.0
        union = expected_tokens | actual_tokens
        if not union:
            return 1.0
        intersection = expected_tokens & actual_tokens
        return len(intersection) / len(union)
