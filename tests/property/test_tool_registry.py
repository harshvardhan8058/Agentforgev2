"""Property-based tests for the Tool_Registry (Properties 5, 6).

These run keyless with lightweight fake tools so the register/resolve/list contract is
exercised in isolation — no orchestrator, no providers, no network.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.tools.base import Tool_Interface, Tool_Result
from agentforge.tools.registry import DuplicateToolNameError, Tool_Registry


class _FakeTool(Tool_Interface):
    """A minimal Tool double with configurable name/description/schema/availability."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        available: bool = True,
    ) -> None:
        self._name = name
        self._description = description
        self._schema = input_schema
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict:
        return self._schema

    @property
    def available(self) -> bool:
        return self._available

    def invoke(self, arguments: dict) -> Tool_Result:
        return Tool_Result(tool_name=self._name, ok=True, content="ok")


@st.composite
def _distinct_tools(draw):
    """Build a list of tools with pairwise-distinct names and varied availability."""
    names = draw(
        st.lists(st.text(min_size=1, max_size=12), min_size=0, max_size=8, unique=True)
    )
    tools = []
    for name in names:
        description = draw(st.text(max_size=24))
        available = draw(st.booleans())
        schema = {"type": "object", "properties": {name: {"type": "string"}}}
        tools.append(_FakeTool(name, description, schema, available))
    return tools


# Feature: agentforge-agentic-layer, Property 5: Tool registry register/resolve/list
# round-trip.
@hyp_settings(max_examples=100, deadline=None)
@given(tools=_distinct_tools(), missing_name=st.text(min_size=1, max_size=12))
def test_registry_register_resolve_list_round_trip(tools, missing_name):
    """Feature: agentforge-agentic-layer, Property 5: For any set of tools with
    pairwise-distinct names, after registering all of them the registry resolves each
    name back to the exact tool registered, returns None for any unregistered name, and
    list_specs() returns exactly the name/description/input schema of each registered
    available tool.

    Validates: Requirements 2.2, 2.3
    """
    registry = Tool_Registry()
    for tool in tools:
        registry.register(tool)

    names = {tool.name for tool in tools}

    # Each registered name resolves back to the exact tool instance.
    for tool in tools:
        assert registry.resolve(tool.name) is tool

    # Any unregistered name resolves to None.
    if missing_name not in names:
        assert registry.resolve(missing_name) is None

    # list_specs returns exactly the specs of the AVAILABLE tools.
    specs = registry.list_specs()
    expected = [
        (tool.name, tool.description, tool.input_schema)
        for tool in tools
        if tool.available
    ]
    actual = [(spec.name, spec.description, spec.input_schema) for spec in specs]
    assert actual == expected


# Feature: agentforge-agentic-layer, Property 6: Duplicate tool-name registration is
# rejected.
@hyp_settings(max_examples=100, deadline=None)
@given(
    name=st.text(min_size=1, max_size=12),
    desc_a=st.text(max_size=24),
    desc_b=st.text(max_size=24),
)
def test_registry_rejects_duplicate_names(name, desc_a, desc_b):
    """Feature: agentforge-agentic-layer, Property 6: For any registered tool and any
    second tool sharing its name, registering the second tool raises a duplicate-tool-name
    error and leaves the originally registered tool resolvable and unchanged.

    Validates: Requirements 2.4
    """
    registry = Tool_Registry()
    first = _FakeTool(name, desc_a, {"type": "object"})
    second = _FakeTool(name, desc_b, {"type": "object", "properties": {}})

    registry.register(first)

    import pytest

    with pytest.raises(DuplicateToolNameError):
        registry.register(second)

    # The incumbent is left untouched (no overwrite).
    assert registry.resolve(name) is first
