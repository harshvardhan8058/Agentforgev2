"""Smoke tests asserting the pluggable-seam interfaces are abstract (Req 1.2, 10.1, 11.1).

Each base class must not be directly instantiable and must declare the abstract
operations the design specifies. This guards the "interfaces over implementations"
rule: the service layer depends on these contracts, never on concrete classes.
"""

from __future__ import annotations

import inspect

import pytest

from agentforge.embeddings.base import Embedding_Provider
from agentforge.llm.base import LLM_Provider
from agentforge.vectorstore.base import Vector_Store


@pytest.mark.parametrize(
    "cls",
    [Embedding_Provider, Vector_Store, LLM_Provider],
)
def test_interface_is_abstract(cls):
    """The abstract base class cannot be instantiated directly."""
    assert inspect.isabstract(cls)
    with pytest.raises(TypeError):
        cls()  # type: ignore[abstract]


@pytest.mark.parametrize(
    ("cls", "expected_methods"),
    [
        (Embedding_Provider, {"dimension", "embed_text", "embed_batch"}),
        (Vector_Store, {"upsert", "query", "delete_document", "count"}),
        (LLM_Provider, {"name", "generate"}),
    ],
)
def test_interface_declares_required_abstract_methods(cls, expected_methods):
    """Each interface declares exactly the abstract operations from the design."""
    assert expected_methods.issubset(cls.__abstractmethods__)


def test_incomplete_implementation_still_abstract():
    """A subclass that omits an abstract method remains non-instantiable."""

    class PartialLLM(LLM_Provider):
        @property
        def name(self) -> str:  # implements only one of two abstract members
            return "partial"

    with pytest.raises(TypeError):
        PartialLLM()  # type: ignore[abstract]
