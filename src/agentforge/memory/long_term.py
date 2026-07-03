"""Long_Term_Memory — semantic recall over existing seams (stub).

Will persist entries by embedding text through the existing ``Embedding_Provider`` and
upserting into the existing ``Vector_Store`` under an ``ltm:<conversation_id>`` namespace,
and retrieve at most ``min(K, stored_count)`` entries by descending similarity — with no
reimplementation of embedding or vector storage (Req 7.1-7.5, 12.3). Implemented in a
later task (see task 10.1); this module is a scaffolding placeholder.
"""

from __future__ import annotations
