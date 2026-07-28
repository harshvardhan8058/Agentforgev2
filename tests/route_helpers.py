"""Route-introspection helpers shared by the wiring/auth-surface tests.

Why this exists
---------------
Several tests assert **security invariants by introspection** rather than by calling
endpoints — e.g. "every Phase 6 route declares ``get_current_principal`` +
``require_permission``". Those assertions need the concrete ``APIRoute`` objects (they
read ``route.dependant``), so they must be able to enumerate the app's real route set.

FastAPI changed how ``include_router`` stores routes. Older versions **copied** each
router's routes onto ``app.routes``, so a flat scan of ``app.routes`` saw everything.
Newer versions (>= 0.140) instead append a single ``_IncludedRouter`` delegate per
``include_router`` call and keep the routes on the original ``APIRouter``, so a flat scan
of ``app.routes`` finds **no** ``APIRoute`` at all — which would silently turn every
"for each route, assert auth is declared" test into a vacuous pass over an empty list.

``iter_api_routes`` walks the route tree so those invariants keep holding regardless of
which layout the installed FastAPI uses. Paths are already absolute (each router carries
its own prefix), so no prefix joining is needed.
"""

from __future__ import annotations

from typing import Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute


def iter_api_routes(app: FastAPI) -> Iterator[APIRoute]:
    """Yield every ``APIRoute`` reachable from ``app``, descending into included routers.

    Handles all three shapes a route entry can take:

    * ``APIRoute``                     — a directly-registered operation (yielded).
    * ``_IncludedRouter``              — a delegate exposing ``.original_router``.
    * ``Mount`` / ``APIRouter``        — anything else carrying a ``.routes`` list.

    Traversal is depth-first and cycle-safe (routers can be included more than once, and
    a shared router object would otherwise be revisited).
    """
    seen: set[int] = set()

    def _walk(routes: object) -> Iterator[APIRoute]:
        for route in routes or ():  # type: ignore[union-attr]
            if id(route) in seen:
                continue
            seen.add(id(route))

            if isinstance(route, APIRoute):
                yield route
                continue

            # Newer FastAPI: include_router() appends a delegate that holds the routes on
            # the router it was built from.
            nested = getattr(route, "original_router", None)
            if nested is not None:
                yield from _walk(getattr(nested, "routes", ()))
                continue

            # Mounts / sub-applications / plain APIRouters.
            nested_routes = getattr(route, "routes", None)
            if nested_routes:
                yield from _walk(nested_routes)

    yield from _walk(app.routes)


def api_route_paths(app: FastAPI) -> set[str]:
    """The set of absolute paths of every mounted ``APIRoute``."""
    return {route.path for route in iter_api_routes(app)}


def dependency_calls(dependant: object) -> list[object]:
    """Flatten a route's dependency tree into the list of callables it resolves.

    Used to assert that an authentication/authorization dependency is present somewhere in
    a route's dependency graph, however deeply it is nested.
    """
    calls = [getattr(dependant, "call", None)]
    for sub in getattr(dependant, "dependencies", ()):
        calls.extend(dependency_calls(sub))
    return calls
