"""Property-based test for prompt versioning + rendering (Task 6.4).

Feature: agentforge-observability, Property 7: Prompt versioning is monotonic, contiguous,
immutable; rendering is total-or-errors. For any organization and template name, creating
a sequence of N Prompt_Versions assigns version numbers forming exactly the contiguous set
{1, 2, ..., N} with no gaps or duplicates in creation order; get_latest returns the
highest-numbered version, get(name, k) returns exactly the version created as number k,
list_versions returns the numbers ascending, and no previously created version's body or
variables ever changes; and for any version and value map, rendering substitutes every
declared variable when all are supplied, whereas rendering raises
AppError("missing_variable", 400) (listing the missing names) whenever at least one
declared variable is omitted.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 11.5
"""

from __future__ import annotations

import uuid

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.api.errors import AppError
from agentforge.observability.prompt_registry.registry import Prompt_Registry
from agentforge.observability.prompt_registry.store import InMemory_Prompt_Store

_names = st.sampled_from(["greeting", "summary", "qa", "system"])
_var_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=6
)


# Feature: agentforge-observability, Property 7: Prompt versioning is monotonic,
# contiguous, immutable; rendering is total-or-errors.
@hyp_settings(max_examples=100, deadline=None)
@given(
    org_id=st.uuids(),
    create_names=st.lists(_names, min_size=0, max_size=8),
    variables=st.lists(_var_names, min_size=0, max_size=4, unique=True),
)
def test_prompt_versioning_and_rendering(org_id, create_names, variables):
    store = InMemory_Prompt_Store()
    registry = Prompt_Registry(store)

    # Track expected version numbers per name and snapshot each created version.
    per_name_count: dict[str, int] = {}
    created: list = []
    for name in create_names:
        expected_n = per_name_count.get(name, 0) + 1
        v = registry.create_version(
            org_id, name, body="hello", variables=variables
        )
        # Monotonic + contiguous: version == prior count + 1 (Req 4.1, 4.9).
        assert v.version == expected_n
        per_name_count[name] = expected_n
        created.append(v)

    # For each distinct name, versions form exactly {1..N} ascending (Req 4.5).
    for name, count in per_name_count.items():
        assert store.list_versions(org_id, name) == list(range(1, count + 1))
        # get_latest returns the highest-numbered version (Req 4.3).
        assert registry.get(org_id, name).version == count
        # get(name, k) returns exactly version k (Req 4.4).
        for k in range(1, count + 1):
            assert registry.get(org_id, name, version=k).version == k

    # Immutability: no created version's body/variables changed (frozen dataclass) (Req 4.2).
    for v in created:
        fetched = registry.get(org_id, v.template_name, version=v.version)
        assert fetched.body == v.body
        assert fetched.variables == v.variables

    # Rendering: all declared variables supplied -> substituted string (Req 4.6).
    if created:
        target = created[-1]
        body = "".join("{" + var + "}" for var in variables) or "static"
        vfull = registry.create_version(
            org_id, target.template_name, body=body, variables=variables
        )
        complete = {var: f"val-{var}" for var in variables}
        rendered = registry.render(vfull, complete)
        for var in variables:
            assert "{" + var + "}" not in rendered
            assert f"val-{var}" in rendered

        # Omitting any declared variable -> AppError("missing_variable", 400) listing it.
        if variables:
            omit = variables[0]
            partial = {var: f"val-{var}" for var in variables if var != omit}
            try:
                registry.render(vfull, partial)
                raise AssertionError("expected missing_variable AppError")
            except AppError as exc:
                assert exc.code == "missing_variable"
                assert exc.status_code == 400
                assert omit in exc.details["missing"]


def test_get_missing_prompt_raises_404():
    """A get for a non-existent prompt raises AppError(not_found, 404)."""
    registry = Prompt_Registry(InMemory_Prompt_Store())
    try:
        registry.get(uuid.uuid4(), "nope")
        raise AssertionError("expected not_found AppError")
    except AppError as exc:
        assert exc.code == "not_found"
        assert exc.status_code == 404
