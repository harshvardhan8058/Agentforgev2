"""Named per-model cost-rate presets, and the resolution order that applies them.

Costs default to ``0`` (Req 2.4), which is correct for the keyless stack — the Fallback
provider runs locally and genuinely costs nothing — but it also meant that a deployment
which *did* set ``GROQ_API_KEY`` still reported ``$0.00`` for every run until an operator
hand-authored a JSON rate table. The analytics dashboards were therefore accurate and
useless at the same time. A preset closes that gap with one environment variable.

Resolution order, lowest precedence first (see :func:`resolve_rate_table`):

1. the default per-1K rates (``cost_default_*_per_1k``) for any unlisted pair — applied by
   :class:`~agentforge.observability.cost.Default_Cost_Model`, not here;
2. the named preset selected by ``cost_rate_preset``, if any;
3. explicit ``cost_rate_table_json`` entries, which override preset entries pair by pair.

Design constraints this file must not break:

* **Keyless stays free and deterministic.** No preset is active unless
  ``cost_rate_preset`` is set, so the default configuration still prices every call at
  ``Decimal("0")``.
* **A typo is a startup failure, not silent mispricing.** An unknown preset name raises
  ``ValueError`` from :func:`resolve_rate_table`, which the composition root calls during
  boot. Reporting fabricated-looking costs (or silently zero ones) because a name was
  misspelled would be worse than refusing to start.
* **Rates are indicative, not authoritative.** Vendor list prices change, and a
  deployment may hold negotiated or batch-discounted rates. Presets are therefore dated
  in their names, documented as a starting point, and overridable per pair.

Rate sources (public on-demand list prices, per **million** tokens, converted to the
per-1K figures below): [Groq on-demand pricing](https://groq.com/pricing) and
[Groq's Llama 3.3 70B announcement](https://groq.com/blog/new-ai-inference-speed-benchmark-for-llama-3-3-70b-powered-by-groq),
cross-checked against [CloudZero's Groq pricing breakdown](https://www.cloudzero.com/blog/groq-pricing/).
Content was rephrased for compliance with licensing restrictions.
"""

from __future__ import annotations

from decimal import Decimal

from agentforge.observability.cost import Rate, parse_rate_table

# ``groq-public-2026-07`` — Groq's published pay-as-you-go rates as of 2026-07, for the
# models this platform can actually select. Quoted per 1K tokens: the vendor publishes
# per 1M, so $0.05/1M is 0.00005/1K.
#
#   llama-3.1-8b-instant     $0.05 /1M in, $0.08 /1M out   (the Groq_Provider default)
#   llama-3.3-70b-versatile  $0.59 /1M in, $0.79 /1M out
_GROQ_PUBLIC_2026_07: dict[tuple[str, str], Rate] = {
    ("groq", "llama-3.1-8b-instant"): Rate(
        prompt_per_1k=Decimal("0.00005"), completion_per_1k=Decimal("0.00008")
    ),
    ("groq", "llama-3.3-70b-versatile"): Rate(
        prompt_per_1k=Decimal("0.00059"), completion_per_1k=Decimal("0.00079")
    ),
}

# Immutable registry of the shipped presets. Adding a preset is a single-file edit here;
# no call site changes (mirroring the RBAC role->permission map's shape).
RATE_PRESETS: dict[str, dict[tuple[str, str], Rate]] = {
    "groq-public-2026-07": _GROQ_PUBLIC_2026_07,
}


def preset_names() -> list[str]:
    """Return the shipped preset names in a stable order (for errors and docs)."""
    return sorted(RATE_PRESETS)


def preset_rates(preset: str) -> dict[tuple[str, str], Rate]:
    """Return a copy of ``preset``'s rate table.

    Raises:
        ValueError: if ``preset`` is not a shipped preset name. Raised rather than
            defaulted so a misspelled name fails at startup instead of quietly pricing
            every call at the default rate.
    """
    try:
        table = RATE_PRESETS[preset]
    except KeyError:
        raise ValueError(
            f"Unknown cost rate preset {preset!r}. "
            f"Known presets: {', '.join(preset_names())}."
        ) from None
    return dict(table)


def resolve_rate_table(
    preset: str | None, rate_table_json: str | None
) -> dict[tuple[str, str], Rate]:
    """Merge a named preset with explicit ``cost_rate_table_json`` overrides.

    Explicit entries win per ``(provider, model)`` pair, so a deployment can adopt a
    preset wholesale and still correct the one model it has negotiated rates for, without
    restating the rest.

    Raises:
        ValueError: if ``preset`` is set but not a shipped preset name.
    """
    table: dict[tuple[str, str], Rate] = {} if preset is None else preset_rates(preset)
    table.update(parse_rate_table(rate_table_json))
    return table
