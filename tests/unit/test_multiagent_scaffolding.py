"""Structural/smoke tests for the Phase 4 multiagent package (Task 1.1).

Assert the ``multiagent`` submodules import cleanly, that the declared seams
(``Agent_Role_Interface``, ``Approval_Policy``, ``Multi_Agent_Run_Store``) are abstract
and cannot be instantiated, and that the new multi-agent settings exist with keyless
defaults (Req 1.1, 5.7).
"""

from __future__ import annotations

import importlib

import pytest

from tests.conftest import apply_base_env

_SUBMODULES = [
    "agentforge.multiagent",
    "agentforge.multiagent.models",
    "agentforge.multiagent.state",
    "agentforge.multiagent.orchestrator",
    "agentforge.multiagent.graph",
    "agentforge.multiagent.approval",
    "agentforge.multiagent.streaming",
    "agentforge.multiagent.store",
    "agentforge.multiagent.roles",
    "agentforge.multiagent.roles.base",
    "agentforge.multiagent.roles.planner",
    "agentforge.multiagent.roles.researcher",
    "agentforge.multiagent.roles.writer",
    "agentforge.multiagent.roles.critic",
]


@pytest.mark.parametrize("module_name", _SUBMODULES)
def test_submodules_import_cleanly(module_name):
    """Every multiagent submodule imports without error."""
    assert importlib.import_module(module_name) is not None


def test_seam_interfaces_are_abstract():
    """The declared seams are ABCs that cannot be instantiated directly (Req 1.1, 5.7)."""
    from agentforge.multiagent.approval import Approval_Policy
    from agentforge.multiagent.roles.base import Agent_Role_Interface
    from agentforge.multiagent.store import Multi_Agent_Run_Store

    for interface in (Agent_Role_Interface, Approval_Policy, Multi_Agent_Run_Store):
        with pytest.raises(TypeError):
            interface()  # type: ignore[abstract]


def test_new_settings_default_keyless(monkeypatch):
    """The Phase 4 settings are optional and default to keyless-safe values (Req 5.7)."""
    apply_base_env(monkeypatch)
    monkeypatch.delenv("MAX_ROUNDS", raising=False)
    monkeypatch.delenv("MAX_REVISIONS", raising=False)
    monkeypatch.delenv("APPROVAL_POLICY", raising=False)

    from agentforge.config.settings import load_settings

    settings = load_settings()

    assert settings.max_rounds is None
    assert settings.max_revisions is None
    assert settings.approval_policy == "auto"
