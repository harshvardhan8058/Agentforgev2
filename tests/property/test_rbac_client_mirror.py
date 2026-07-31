"""Property: the client RBAC mirror never drifts from the server's permission vocabulary.

``frontend/src/auth/rbac.ts`` is a hand-maintained mirror of ``enterprise/rbac.py``: it
exists so RBAC-gated UI is a pure function of the Session Role, with no round trip. That
design is sound, but nothing kept the two files in agreement, and the two failure modes are
opposite and both bad:

* a permission added on the **server** and forgotten on the client makes the UI hide an
  affordance the caller is in fact authorized to use — a silent capability regression that
  no test would notice, because omitting a control is exactly what the client does for an
  unauthorized role;
* a permission present only on the **client** makes the UI offer a control the server will
  refuse with a 403 — a defect the user discovers by being rejected.

This test reads the committed TypeScript and compares its permission vocabulary and its
role → permission map to the authoritative Python. It is keyless, deterministic, and needs
no build step or Node runtime: the mirror is a static declaration, so parsing it is enough.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentforge.enterprise.rbac import ROLE_PERMISSIONS, Permission, Role

_MIRROR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "auth" / "rbac.ts"

# Each `const NAME: ReadonlySet<Permission> = new Set<Permission>([ ... ]);` block, where
# the body may spread a previously-defined set (`...MEMBER`) and/or list literals.
_SET_BLOCK = re.compile(
    r"const\s+(?P<name>[A-Z]+):\s*ReadonlySet<Permission>\s*=\s*new Set<Permission>\("
    r"\s*\[(?P<body>.*?)\]\s*\)",
    re.DOTALL,
)
_QUOTED = re.compile(r'"([a-z_]+)"')
_SPREAD = re.compile(r"\.\.\.([A-Z]+)")

# `viewer: VIEWER,` entries inside the exported ROLE_PERMISSIONS record.
_MAP_ENTRY = re.compile(r"^\s*(?P<role>owner|admin|member|viewer):\s*(?P<set>[A-Z]+),")


def _mirror_source() -> str:
    assert _MIRROR.exists(), f"client RBAC mirror not found at {_MIRROR}"
    return _MIRROR.read_text(encoding="utf-8")


def _declared_permission_union(source: str) -> set[str]:
    """Return the members of the exported ``Permission`` union type."""
    match = re.search(
        r"export type Permission =(?P<body>.*?);", source, re.DOTALL
    )
    assert match is not None, "no `export type Permission` union found in the mirror"
    return set(_QUOTED.findall(match.group("body")))


def _resolved_sets(source: str) -> dict[str, set[str]]:
    """Resolve each declared set, expanding spreads of earlier sets."""
    resolved: dict[str, set[str]] = {}
    for block in _SET_BLOCK.finditer(source):
        body = block.group("body")
        members = set(_QUOTED.findall(body))
        for spread in _SPREAD.findall(body):
            assert spread in resolved, f"{spread} is spread before it is declared"
            members |= resolved[spread]
        resolved[block.group("name")] = members
    assert resolved, "no permission sets found in the mirror"
    return resolved


def _mirror_role_map(source: str) -> dict[str, set[str]]:
    """Return the client's ``role -> permissions`` map, by resolving its set references."""
    sets = _resolved_sets(source)
    mapping: dict[str, set[str]] = {}
    for line in source.splitlines():
        entry = _MAP_ENTRY.match(line)
        if entry is None:
            continue
        set_name = entry.group("set")
        assert set_name in sets, f"role {entry.group('role')} references unknown {set_name}"
        mapping[entry.group("role")] = sets[set_name]
    return mapping


def test_client_permission_vocabulary_matches_the_server():
    server = {permission.value for permission in Permission}
    client = _declared_permission_union(_mirror_source())

    assert client == server, (
        "frontend/src/auth/rbac.ts is out of sync with enterprise/rbac.py — "
        f"only on the server: {sorted(server - client)}; "
        f"only on the client: {sorted(client - server)}"
    )


def test_client_role_map_matches_the_server_exactly():
    server = {
        role.value: {permission.value for permission in permissions}
        for role, permissions in ROLE_PERMISSIONS.items()
    }
    client = _mirror_role_map(_mirror_source())

    assert client == server


@pytest.mark.parametrize("role", list(Role))
def test_every_client_role_is_declared(role: Role):
    """A missing role would make `can()` throw on a valid token, not merely under-grant."""
    assert role.value in _mirror_role_map(_mirror_source())
