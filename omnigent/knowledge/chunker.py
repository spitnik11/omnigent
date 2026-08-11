"""Heading-aware markdown chunking. Keeps the heading path so retrieval can cite it."""
from __future__ import annotations

import re

_H = re.compile(r"^(#{1,6})\s+(.*)")


def chunk_markdown(text: str, max_chars: int = 1200) -> list[tuple[str, str]]:
    heading: list[str] = []
    buf: list[str] = []
    out: list[tuple[str, str]] = []

    def flush():
        content = "\n".join(buf).strip()
        buf.clear()
        if content:
            out.append((" > ".join(heading), content))

    for ln in (text or "").splitlines():
        m = _H.match(ln)
        if m:
            flush()
            level = len(m.group(1))
            heading[:] = heading[:level - 1] + [m.group(2).strip()]
        else:
            buf.append(ln)
            if sum(len(x) for x in buf) > max_chars:
                flush()
    flush()

    # hard-split anything still oversized
    final: list[tuple[str, str]] = []
    for hp, c in out:
        while len(c) > int(max_chars * 1.5):
            final.append((hp, c[:max_chars]))
            c = c[max_chars:]
        final.append((hp, c))
    return final
