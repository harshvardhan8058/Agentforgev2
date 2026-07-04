"""Multi_Agent_Layer (Phase 4) — multi-agent collaboration and human approval.

Four specialized agents (Planner, Researcher, Writer, Critic) collaborate on a single task
through a bounded, terminating LangGraph orchestration graph, sharing a typed
``Blackboard_State``, driving a bounded revision loop, and pausing at defined checkpoints
for a human approval workflow. The whole layer **reuses — never reimplements** the Phase
1-3 seams (``Agent_Orchestrator``, ``Tool_Registry``, ``RAG_Tool``, ``Memory_Manager``,
``LLM_Provider``/``Fallback_Provider``, ``Streaming_Service``, ``Trace_Recorder``,
``Conversation_Store``, and the ``API_Service``), and stays fully runnable and testable
with no external credentials.
"""

from __future__ import annotations
