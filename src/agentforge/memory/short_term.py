"""Short_Term_Memory — Size_Budget-bounded FIFO working context (stub).

Will validate the Size_Budget, maintain the run's working context, and FIFO-evict
oldest-first (excluding the current user request) to keep the retained size within budget
(Req 6.1-6.6). Implemented in a later task (see task 9.1); this module is a scaffolding
placeholder.
"""

from __future__ import annotations
