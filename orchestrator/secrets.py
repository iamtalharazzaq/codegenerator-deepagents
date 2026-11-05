"""Secret scan over the generated code, run before anything is delivered. Findings never echo the secret."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})
MAX_SCAN_BYTES = 1_000_000

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("api_secret_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{24,}")),
    (
        "hardcoded_credential",
        re.compile(r"""(?i)\b(?:api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*['"]([^'"\s]{12,})['"]"""),
    ),
)
_PLACEHOLDER = re.compile(r"(?i)example|changeme|your[_-]|xxx|placeholder|<|\$\{|dummy|sample|test")


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    kind: str


def _is_env_file(name: str) -> bool:
    return name == ".env" or (name.startswith(".env.") and not name.endswith((".example", ".sample", ".template")))


def scan_secrets(root: Path) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    if not root.exists():
        return findings
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(p in SKIP_DIRS for p in rel.parts) or not path.is_file() or path.is_symlink():
            continue
        if _is_env_file(path.name) or path.stat().st_size > MAX_SCAN_BYTES:
            continue  # real .env files are left out of the zip anyway
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in _PATTERNS:
                match = pattern.search(line)
                if match is None:
                    continue
                value = match.group(1) if match.groups() else match.group(0)
                if kind == "hardcoded_credential" and _PLACEHOLDER.search(value):
                    continue
                findings.append(SecretFinding(rel.as_posix(), number, kind))
                break
    return findings
