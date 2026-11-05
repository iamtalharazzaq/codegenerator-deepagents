"""Zip delivery: the project files at the root, the report and role artifacts under `docs/orchestrator/`.

Left out: `.git`, `node_modules`, virtualenvs, caches, real `.env` files, symlinks."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from orchestrator.secrets import SKIP_DIRS

DOCS_PREFIX = "docs/orchestrator"
_ARTIFACT_RE = re.compile(r"^[0-9a-f]{8}\.md$")  # the latest artifact per task; per-attempt copies stay out
EXCLUDED_SUFFIXES = (".pyc",)


def _excluded(rel: Path) -> bool:
    if any(p in SKIP_DIRS for p in rel.parts):
        return True
    name = rel.name
    if name == ".env" or (name.startswith(".env.") and not name.endswith((".example", ".sample", ".template"))):
        return True
    return name.endswith(EXCLUDED_SUFFIXES)


def build_zip(work: Path, run_dir: Path, dest: Path, *, partial: bool = False) -> tuple[Path, int]:
    """Write the delivery zip. Returns (path, number of files)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        if work.exists():
            for path in sorted(work.rglob("*")):
                rel = path.relative_to(work)
                if path.is_symlink() or not path.is_file() or _excluded(rel):
                    continue
                zf.write(path, rel.as_posix())
                count += 1
        for name in ["report.md", *sorted(p.name for p in run_dir.glob("*.md") if _ARTIFACT_RE.match(p.name))]:
            source = run_dir / name
            if source.is_file():
                zf.write(source, f"{DOCS_PREFIX}/{name}")
                count += 1
        if partial:
            zf.writestr("PARTIAL.txt", "This run did not finish. See docs/orchestrator/report.md for what is missing.\n")
    return dest, count
