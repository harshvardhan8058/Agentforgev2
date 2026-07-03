"""Smoke test asserting the Tool_Interface contract is abstract (Req 2.1)."""

from __future__ import annotations

import inspect

import pytest

from agentforge.tools.base import Tool_Interface


def test_tool_interface_is_abstract():
    """Tool_Interface cannot be instantiated directly."""
    assert inspect.isabstract(Tool_Interface)
    with pytest.raises(TypeError):
        Tool_Interface()  # type: ignore[abstract]


def test_tool_interface_declares_required_abstract_members():
    """Tool_Interface declares the name/description/input_schema/invoke abstract members."""
    expected = {"name", "description", "input_schema", "invoke"}
    assert expected.issubset(Tool_Interface.__abstractmethods__)


def test_incomplete_tool_still_abstract():
    """A subclass omitting an abstract member remains non-instantiable."""

    class PartialTool(Tool_Interface):
        @property
        def name(self) -> str:  # implements only one of the abstract members
            return "partial"

    with pytest.raises(TypeError):
        PartialTool()  # type: ignore[abstract]
