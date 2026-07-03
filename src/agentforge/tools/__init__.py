"""Tools (Phase 3): the Tool interface, registry, and built-in tools.

The agent core depends only on the abstract ``Tool_Interface`` and ``Tool_Registry``
declared here, so a new capability is added by implementing the interface and
registering it — never by editing the orchestrator (Req 2.5). Built-in tools
(``RAG_Tool``, ``Web_Search_Tool``) and the pluggable ``Search_Provider`` live in
sibling modules.
"""

from __future__ import annotations
