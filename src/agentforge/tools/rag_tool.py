"""RAG_Tool — built-in tool wrapping the existing RAG_Service (stub).

Will implement ``Tool_Interface`` with an input schema accepting a ``query`` (required)
and optional ``top_k``, delegating to the injected ``RAG_Service`` and returning a
``Tool_Result`` carrying the answer text plus citations/grounded/provider — with no
reimplementation of retrieval or generation (Req 4.1-4.4, 12.2). Implemented in a later
task (see task 5.1); this module is a scaffolding placeholder.
"""

from __future__ import annotations
