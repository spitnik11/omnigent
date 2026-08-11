"""ObsidianWriter — Omni's durable memory, written ONLY under _Omni/**.

Hard safety: never touches a note that isn't already `omni_managed: true`. If the
vault isn't configured, falls back to Omni's state dir so memory is never lost.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .config import STATE_DIR
from .sources import parse_frontmatter
from .types import MemoryRecord

_KIND_DIR = {"run-summary": "Runs", "review-learning": "Reviews", "research": "Research",
             "decision": "Decisions", "convention": "Conventions", "constraint": "Constraints"}


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:48] or "note"


class ObsidianWriter:
    def __init__(self, vault_path: str = "", write_root: str = "_Omni"):
        self.base = (Path(vault_path) / write_root) if vault_path else (STATE_DIR / "knowledge" / "memory")
        self.in_vault = bool(vault_path)

    def _path(self, m: MemoryRecord) -> Path:
        sub = _KIND_DIR.get(m.kind, "Notes")
        return self.base / "Projects" / (m.project or "global") / sub / f"{_slug(m.title)}.md"

    def write(self, m: MemoryRecord) -> str | None:
        try:
            target = self._path(m)
            if target.exists():
                meta, _ = parse_frontmatter(target.read_text(encoding="utf-8", errors="replace"))
                if not meta.get("omni_managed"):
                    return None  # refuse to overwrite a human note — non-fatal
            target.parent.mkdir(parents=True, exist_ok=True)
            today = date.today().isoformat()
            fm = ["---", "omni_managed: true", "omni_schema: 1", f"kind: {m.kind}",
                  f"project: {m.project}"]
            if m.run_id:
                fm.append(f"run_id: {m.run_id}")
            fm.append(f"status: {m.status}")
            if m.source_commits:
                fm.append("source_commit:")
                fm += [f"  - {c}" for c in m.source_commits if c]
            fm += [f"created: {today}", f"updated: {today}", "---", ""]
            target.write_text("\n".join(fm) + m.body.rstrip() + "\n", encoding="utf-8")
            return str(target)
        except Exception:
            return None  # writing memory must never fail a run
