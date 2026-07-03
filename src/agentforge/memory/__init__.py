"""Memory (Phase 3): short-term working context and long-term semantic recall.

The abstract ``Memory_Manager`` (``base.py``) provides short-term memory (a Size_Budget
FIFO working context, ``short_term.py``) and long-term memory (semantic recall over the
existing Embedding_Provider + Vector_Store, ``long_term.py``) to the orchestrator
(Req 6, 7, 12.3).
"""

from __future__ import annotations
