"""Web_Search_Tool — built-in web search with graceful degradation (stub).

Will implement ``Tool_Interface`` with a ``query`` input schema, mirror the injected
``Search_Provider``'s availability, and return an "unavailable" ``Tool_Result`` (with no
network request) when the provider is disabled (Req 5.1, 5.2, 5.4, 5.5). Implemented in a
later task (see task 6.2); this module is a scaffolding placeholder.
"""

from __future__ import annotations
