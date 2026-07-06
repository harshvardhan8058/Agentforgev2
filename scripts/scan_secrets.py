#!/usr/bin/env python3
"""Cross-image / repo-wide secret scanner (Phase 9, Property 1, Req 10.2, 10.3, 3.3, 8.5).

Extends the frontend bundle-secret scan concept
(``frontend/scripts/scan-bundle-secrets.mjs``) to a repo/image-wide scanner. It asserts
that **no real credential-shaped value** appears in any place a credential could be
baked in or served:

  * committed ``*.env.example`` / ``.env.production.example`` files (placeholders only);
  * the built frontend assets under ``frontend/dist`` (incl. the generated ``config.js``),
    when present;
  * the runtime ``config.js`` rendered from the frontend template for arbitrary,
    non-secret ``API_BASE_URL`` values (build-once / run-anywhere);
  * image layers — via ``--image-tar`` on a ``docker save`` tarball (wired into the CI
    ``build`` job, where live image builds are available).

Design points
-------------
* The scan matches actual **secret patterns / env leakage** (token & key *shapes*, PEM
  blocks, and secret-bearing assignments with non-placeholder values) rather than the
  mere presence of a word like "password" or "token", so it does not false-positive on
  placeholders (``REPLACE_*``, empty values, ``${VAR}`` interpolation) or benign
  framework strings (``Authorization``/``Bearer`` header *names*, an
  ``<input type="password">`` type list, etc.).
* Pure helpers (``scan_text``, ``render_config_js``, ``scan_env_examples``,
  ``scan_frontend_dist``, ``scan_repo``, ``scan_image_tar``) are imported directly by the
  Property 1 test (``tests/property/test_deployment_no_baked_secrets.py``).

Usage
-----
    python scripts/scan_secrets.py                     # scan repo sources (exit 1 on finding)
    python scripts/scan_secrets.py --image-tar img.tar # scan a docker-saved image tarball
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

# Repository root (this file lives in <repo>/scripts/).
REPO_ROOT = Path(__file__).resolve().parents[1]

# Path to the frontend Runtime_Config template rendered at container start.
CONFIG_TEMPLATE = REPO_ROOT / "frontend" / "docker" / "config.js.template"

# The documented default when no API_BASE_URL is supplied (empty runtime config object).
EMPTY_CONFIG_JS = "window.__AGENTFORGE_CONFIG__ = {};\n"


@dataclass(frozen=True)
class Finding:
    """A single secret-scan hit."""

    pattern: str
    where: str
    sample: str

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        return f"[{self.pattern}] {self.sample} in {self.where}"


# ---------------------------------------------------------------------------
# Secret / credential *patterns* — shapes that only real secret material takes.
# Mirrors frontend/scripts/scan-bundle-secrets.mjs and adds env-leak coverage.
# ---------------------------------------------------------------------------
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # JWT (three base64url segments) — a leaked access token looks like this.
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    # Provider API keys.
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9]{20,}\b")),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("stripe-secret-key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    # PEM private-key blocks.
    (
        "private-key-block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ),
    # A secret-bearing key assigned a non-trivial QUOTED literal value (env leakage).
    (
        "secret-assignment",
        re.compile(
            r"\b(?:secret|password|passwd|api[_-]?key|access[_-]?key|secret[_-]?key|"
            r"client[_-]?secret|private[_-]?key|refresh[_-]?token|auth[_-]?token)\b"
            r"\s*[:=]\s*[\"'`][^\"'`\n]{8,}[\"'`]",
            re.IGNORECASE,
        ),
    ),
    # A concrete bearer token literal (header *value*, not the header name).
    ("bearer-token-literal", re.compile(r"Bearer\s+eyJ[A-Za-z0-9_-]{8,}")),
]

# Env-assignment leak scan: KEY=VALUE where KEY is secret-bearing and VALUE is a real,
# non-placeholder value. Applied to *.env.example files (unquoted assignments).
_ENV_SECRET_KEY = re.compile(
    r"^\s*([A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|TOKEN)"
    r"[A-Z0-9_]*)\s*=\s*(\S.*?)\s*$"
)

# Tokens that mark a value as an intentional placeholder (never a real credential).
_PLACEHOLDER_MARKERS = (
    "REPLACE",
    "CHANGE",
    "YOUR_",
    "PLACEHOLDER",
    "EXAMPLE",
    "XXXX",
    "TODO",
    "DUMMY",
    "<",
)


def _is_placeholder(value: str) -> bool:
    """True when an env value is empty, an interpolation, or an obvious placeholder."""
    v = value.strip().strip("\"'")
    if not v:
        return True
    if v.startswith("${") or v.startswith("$("):  # shell / compose interpolation
        return True
    upper = v.upper()
    return any(marker in upper for marker in _PLACEHOLDER_MARKERS)


def _redact(match_text: str) -> str:
    """Keep only a short, redacted excerpt so a report never leaks a secret."""
    head = match_text[:8]
    return f"{head}\u2026" if len(match_text) > 8 else head


def scan_text(text: str, where: str = "<text>") -> list[Finding]:
    """Scan a single text blob for credential-shaped values (pure)."""
    findings: list[Finding] = []
    for name, pattern in SECRET_PATTERNS:
        m = pattern.search(text)
        if m:
            findings.append(Finding(pattern=name, where=where, sample=_redact(m.group(0))))
    return findings


def scan_env_text(text: str, where: str = "<env>") -> list[Finding]:
    """Scan .env-style content: credential shapes + secret keys with non-placeholder values."""
    findings = list(scan_text(text, where))
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue  # comments and blanks are not assignments
        m = _ENV_SECRET_KEY.match(line)
        if m:
            key, value = m.group(1), m.group(2)
            # Strip trailing inline comments for the placeholder check.
            value_no_comment = value.split(" #", 1)[0].strip()
            if not _is_placeholder(value_no_comment):
                findings.append(
                    Finding(
                        pattern="env-secret-value",
                        where=f"{where} ({key})",
                        sample=_redact(value_no_comment),
                    )
                )
    return findings


def render_config_js(api_base_url: str | None) -> str:
    """Render the frontend Runtime_Config ``config.js`` the way the entrypoint does.

    Mirrors ``frontend/docker/entrypoint.sh``: when ``API_BASE_URL`` is set, substitute
    it into the template; otherwise emit the empty config object (documented default).
    """
    if api_base_url:
        template = CONFIG_TEMPLATE.read_text(encoding="utf-8")
        return template.replace("${API_BASE_URL}", api_base_url)
    return EMPTY_CONFIG_JS


def scan_env_examples(root: Path = REPO_ROOT) -> list[Finding]:
    """Scan every committed ``*.env.example`` file (placeholders only)."""
    findings: list[Finding] = []
    for path in sorted(root.rglob("*.env.example")):
        if "node_modules" in path.parts or ".venv" in path.parts:
            continue
        rel = path.relative_to(root)
        findings.extend(scan_env_text(path.read_text(encoding="utf-8"), str(rel)))
    return findings


def scan_frontend_dist(root: Path = REPO_ROOT) -> list[Finding]:
    """Scan the built frontend assets (incl. generated ``config.js``) when present."""
    dist = root / "frontend" / "dist"
    if not dist.is_dir():
        return []
    findings: list[Finding] = []
    scanned_ext = {".js", ".mjs", ".cjs", ".css", ".html", ".map", ".json"}
    for path in sorted(dist.rglob("*")):
        if path.is_file() and path.suffix.lower() in scanned_ext:
            rel = path.relative_to(root)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            findings.extend(scan_text(text, str(rel)))
    return findings


def scan_config_renders(samples: list[str] | None = None) -> list[Finding]:
    """Scan config.js rendered for representative non-secret API_BASE_URL values."""
    if samples is None:
        samples = [
            None,  # type: ignore[list-item]  # unset -> empty config
            "http://localhost:8000",
            "https://agentforge.example.com",
            "/",
        ]
    findings: list[Finding] = []
    for value in samples:
        rendered = render_config_js(value)
        findings.extend(scan_text(rendered, f"config.js(API_BASE_URL={value!r})"))
    return findings


def scan_repo(root: Path = REPO_ROOT) -> list[Finding]:
    """Full repo-wide scan: env examples + built dist + config.js renders."""
    findings: list[Finding] = []
    findings.extend(scan_env_examples(root))
    findings.extend(scan_frontend_dist(root))
    findings.extend(scan_config_renders())
    return findings


def scan_image_tar(tar_path: Path) -> list[Finding]:
    """Scan every text-ish file inside a ``docker save`` image tarball for secrets."""
    findings: list[Finding] = []
    scanned_ext = {
        ".js", ".mjs", ".cjs", ".css", ".html", ".map", ".json", ".env",
        ".conf", ".cfg", ".ini", ".yml", ".yaml", ".sh", ".txt", ".py", ".pem",
    }
    with tarfile.open(tar_path, "r:*") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name_lower = member.name.lower()
            # Nested layer blobs are themselves tarballs; recurse one level.
            if name_lower.endswith((".tar", "layer.tar")) or "/layer" in name_lower:
                fobj = tar.extractfile(member)
                if fobj is None:
                    continue
                try:
                    with tarfile.open(fileobj=fobj, mode="r:*") as inner:
                        for inner_member in inner.getmembers():
                            if not inner_member.isfile():
                                continue
                            if Path(inner_member.name).suffix.lower() in scanned_ext:
                                data = inner.extractfile(inner_member)
                                if data is None:
                                    continue
                                text = data.read().decode("utf-8", errors="ignore")
                                findings.extend(
                                    scan_text(text, f"{tar_path.name}:{inner_member.name}")
                                )
                except tarfile.TarError:
                    continue
            elif Path(member.name).suffix.lower() in scanned_ext:
                data = tar.extractfile(member)
                if data is None:
                    continue
                text = data.read().decode("utf-8", errors="ignore")
                findings.extend(scan_text(text, f"{tar_path.name}:{member.name}"))
    return findings


def _report(findings: list[Finding], scope: str) -> int:
    if findings:
        print(f"Secret scan FAILED — {len(findings)} finding(s) in {scope}:", file=sys.stderr)
        for f in findings:
            print(f"  \u2022 {f}", file=sys.stderr)
        return 1
    print(f"Secret scan passed — no credential-shaped value found in {scope}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentForge cross-image secret scanner")
    parser.add_argument(
        "--image-tar",
        type=Path,
        default=None,
        help="Path to a `docker save` image tarball to scan (image-layer scan).",
    )
    args = parser.parse_args(argv)

    if args.image_tar is not None:
        findings = scan_image_tar(args.image_tar)
        return _report(findings, f"image tar {args.image_tar}")

    findings = scan_repo()
    return _report(findings, "repo sources (*.env.example, frontend/dist, config.js renders)")


if __name__ == "__main__":
    raise SystemExit(main())
