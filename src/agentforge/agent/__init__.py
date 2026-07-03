"""Agent core (Phase 3): the bounded reason -> act -> observe orchestration.

This package holds the agent core: the typed run state (``state.py``), the LangGraph
node functions and edge routing (``graph.py``), the ``Agent_Orchestrator`` that builds
and runs the graph (``orchestrator.py``), and the tool-selection seam plus deterministic
fallback (``selection.py``). The core depends only on the abstract seams in the sibling
``tools``, ``memory``, ``tracing``, and ``streaming`` packages.
"""

from __future__ import annotations
