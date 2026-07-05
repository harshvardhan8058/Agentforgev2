"""Cost_Model seam (Pluggable Seam: cost).

The ``Cost_Model`` maps a ``(provider, model, Token_Count)`` to a monetary ``Cost``
(a :class:`~decimal.Decimal`). It is **total** over its input space: every input maps to
a defined, non-negative cost, applying a default rate when no rate is configured for a
pair (Req 2.5). A new Cost_Model is registered in the composition root without touching
the Instrumented_Provider or the LLM_Provider contract (Req 2.6).

Monetary arithmetic uses :class:`~decimal.Decimal` exclusively so there is no float drift
(Req 2.2). The keyless default rate is ``0`` per 1K tokens, so keyless usage records carry
a deterministic ``Decimal("0")`` cost (Req 2.4, 10.2).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from agentforge.observability.models import Token_Count

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agentforge.config.settings import Settings

# Number of tokens a per-1K rate is quoted against.
_TOKENS_PER_RATE_UNIT = Decimal(1000)


@dataclass(frozen=True)
class Rate:
    """A per-1K-token price pair for a (provider, model) or the default fallback."""

    prompt_per_1k: Decimal
    completion_per_1k: Decimal


class Cost_Model(ABC):
    """Abstract contract mapping (provider, model, Token_Count) -> Cost."""

    @abstractmethod
    def cost_for(self, provider: str, model: str, tokens: Token_Count) -> Decimal:
        """Return the Cost for the call; defined for every input, never raising (Req 2.5)."""
        raise NotImplementedError


class Default_Cost_Model(Cost_Model):
    """Config-driven per-1K-token rate table with a default fallback rate (Req 2.5).

    ``cost_for`` applies the configured rate for a listed ``(provider, model)`` pair and
    the ``default_rate`` for any unlisted pair, computing
    ``prompt/1000 * prompt_per_1k + completion/1000 * completion_per_1k`` with exact
    :class:`~decimal.Decimal` arithmetic.
    """

    def __init__(
        self,
        rates: dict[tuple[str, str], Rate] | None = None,
        default_rate: Rate | None = None,
    ) -> None:
        self._rates: dict[tuple[str, str], Rate] = dict(rates or {})
        self._default_rate: Rate = default_rate or Rate(Decimal(0), Decimal(0))

    def cost_for(self, provider: str, model: str, tokens: Token_Count) -> Decimal:
        """Map ``(provider, model, tokens)`` to a defined, non-negative Cost (Req 2.2, 2.5)."""
        rate = self._rates.get((provider, model), self._default_rate)
        prompt_cost = (
            Decimal(tokens.prompt) / _TOKENS_PER_RATE_UNIT * rate.prompt_per_1k
        )
        completion_cost = (
            Decimal(tokens.completion) / _TOKENS_PER_RATE_UNIT * rate.completion_per_1k
        )
        return prompt_cost + completion_cost


def parse_rate_table(rate_table_json: str | None) -> dict[tuple[str, str], Rate]:
    """Parse a ``cost_rate_table_json`` string into a ``(provider, model) -> Rate`` table.

    The JSON maps a ``"provider:model"`` key to an object with ``prompt`` and
    ``completion`` per-1K rates (as decimal strings), e.g.
    ``{"groq:llama-3.1-8b": {"prompt": "0.05", "completion": "0.08"}}``. A ``None`` or
    empty string yields an empty table so the default rate applies to every pair.
    """
    if not rate_table_json:
        return {}
    raw = json.loads(rate_table_json)
    table: dict[tuple[str, str], Rate] = {}
    for key, value in raw.items():
        provider, _, model = key.partition(":")
        table[(provider, model)] = Rate(
            prompt_per_1k=Decimal(str(value.get("prompt", "0"))),
            completion_per_1k=Decimal(str(value.get("completion", "0"))),
        )
    return table


def build_default_cost_model(settings: Settings) -> Default_Cost_Model:
    """Build a :class:`Default_Cost_Model` from ``Settings`` (invoked by the container).

    Reads the optional ``cost_rate_table_json`` into the rate table and the
    ``cost_default_prompt_per_1k`` / ``cost_default_completion_per_1k`` fields into the
    default fallback rate. On the keyless path both defaults are ``"0.0"``, so the model
    returns ``Decimal("0")`` for every unlisted pair (Req 2.4, 2.5, 10.2).
    """
    rates = parse_rate_table(settings.cost_rate_table_json)
    default_rate = Rate(
        prompt_per_1k=Decimal(str(settings.cost_default_prompt_per_1k)),
        completion_per_1k=Decimal(str(settings.cost_default_completion_per_1k)),
    )
    return Default_Cost_Model(rates=rates, default_rate=default_rate)
