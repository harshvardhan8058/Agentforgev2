"""Enterprise_Layer (Phase 5): auth, identity, RBAC, API keys, rate limiting, tenancy.

This package holds the enterprise core — pure logic over the abstract ``Identity_Store``,
``API_Key_Store``, and ``Rate_Limiter`` seams declared in :mod:`agentforge.enterprise.base`.
Concrete implementations are named only by the composition root
(:mod:`agentforge.config.container`); endpoints depend on the FastAPI dependencies alone.
"""

from __future__ import annotations
