"""Analytics_Service: org-scoped aggregation of Usage_Records into a Usage_Report.

The service computes a :class:`~agentforge.observability.models.Usage_Report` **only**
from records whose ``org_id`` equals the requester's, so no other tenant's usage can ever
appear (Req 3.1, 3.3, 10.5). By construction the report's ``total_tokens`` /
``total_cost`` equal the sum over the included records, and each breakdown
(``by_provider`` / ``by_model`` / ``by_user``) is a partition of that same record set, so
each breakdown's token totals sum to the report total (Req 3.2, 3.4, 3.7).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from agentforge.observability.models import (
    Breakdown_Entry,
    Usage_Record,
    Usage_Report,
)
from agentforge.observability.usage.base import Usage_Store


def _group_sum(
    records: list[Usage_Record], *, key: Callable[[Usage_Record], str]
) -> list[Breakdown_Entry]:
    """Partition ``records`` by ``key`` and sum tokens/cost within each group.

    The union of the groups is exactly ``records`` (a partition), so the per-group token
    sums add back up to the whole record set's total (Req 3.2, 3.7). Groups are returned
    in ascending key order for a deterministic, reproducible report.
    """
    tokens_by_key: dict[str, int] = {}
    cost_by_key: dict[str, Decimal] = {}
    for record in records:
        k = key(record)
        tokens_by_key[k] = tokens_by_key.get(k, 0) + record.total_tokens
        cost_by_key[k] = cost_by_key.get(k, Decimal(0)) + record.cost
    return [
        Breakdown_Entry(
            key=k,
            total_tokens=tokens_by_key[k],
            total_cost=cost_by_key[k],
        )
        for k in sorted(tokens_by_key)
    ]


class Analytics_Service:
    """Queries and aggregates Usage_Records for an Organization over a time range."""

    def __init__(self, store: Usage_Store) -> None:
        self._store = store

    def usage_report(
        self, org_id: UUID, *, start: datetime, end: datetime
    ) -> Usage_Report:
        """Aggregate ``org_id``'s in-range Usage_Records into a Usage_Report.

        Reads **only** ``store.list_for_org(org_id, ...)`` so no other tenant's usage can
        contribute (Req 3.1, 3.3, 10.5). ``total_tokens`` / ``total_cost`` are the sums
        over those records; ``by_provider`` / ``by_model`` / ``by_user`` partition the
        same record set (Req 3.2, 3.4, 3.7).
        """
        records = self._store.list_for_org(org_id, start=start, end=end)
        return Usage_Report(
            org_id=org_id,
            start=start,
            end=end,
            total_tokens=sum(r.total_tokens for r in records),
            total_cost=sum((r.cost for r in records), Decimal(0)),
            by_provider=_group_sum(records, key=lambda r: r.provider),
            by_model=_group_sum(records, key=lambda r: r.model),
            by_user=_group_sum(
                records, key=lambda r: str(r.user_id) if r.user_id is not None else ""
            ),
        )
