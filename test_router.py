"""Router self-check — the one piece of non-trivial logic. Run: python test_router.py"""
from omnigent.harness import Harness
from omnigent.router import route, strip_prefix

CFG = {
    "router": {
        "default": "claude",
        "rules": {
            "grok": ["search", "web"],
            "codex": ["refactor", "pytest"],
        },
    }
}


class _AvailHarness(Harness):
    """Harness with availability forced, so tests don't depend on PATH."""
    def __init__(self, name: str, ok: bool, **kw):
        super().__init__(name=name, bin=name, detect=name, **kw)
        self._ok = ok

    @property
    def available(self) -> bool:  # type: ignore[override]
        return self._ok


def _hs(available: dict[str, bool]) -> dict[str, Harness]:
    return {name: _AvailHarness(name, ok) for name, ok in available.items()}


def main():
    all_up = _hs({"claude": True, "grok": True, "codex": True})

    # keyword routing
    assert route("search the web for X", all_up, CFG) == "grok"
    assert route("refactor this module", all_up, CFG) == "codex"
    # default when no keyword matches
    assert route("write me a poem", all_up, CFG) == "claude"
    # explicit flag override beats keywords
    assert route("search the web", all_up, CFG, forced="claude") == "claude"
    # '@name' prefix override + stripping
    assert route("@grok explain this", all_up, CFG) == "grok"
    assert strip_prefix("@grok explain this", all_up) == "explain this"
    assert strip_prefix("no prefix here", all_up) == "no prefix here"

    # unavailable chosen harness falls back to an available one
    no_grok = _hs({"claude": True, "grok": False, "codex": True})
    assert route("search the web", no_grok, CFG) == "claude"  # grok down -> default
    assert route("@grok do it", no_grok, CFG) == "claude"     # forced-but-down -> fallback

    # unknown forced harness errors
    try:
        route("x", all_up, CFG, forced="nope")
        raise AssertionError("expected error for unknown harness")
    except RuntimeError:
        pass

    # no harnesses available errors
    try:
        route("x", _hs({"claude": False}), CFG)
        raise AssertionError("expected error when nothing available")
    except RuntimeError:
        pass

    # cost-aware routing: role=None (unspecified) behaves exactly as before —
    # keyword rules still decide, no local preference applied.
    assert route("write me a poem", all_up, CFG, role=None) == "claude"

    # IMPLEMENT prefers an available cost:0 local harness whose capabilities match
    with_local = _hs({"claude": True, "codex": True})
    with_local["aider"] = _AvailHarness("aider", True, kind="local", cost=0,
                                        capabilities=["implement"])
    assert route("write me a poem", with_local, CFG, role="IMPLEMENT") == "aider"
    # REVIEW is untouched by the local preference -> falls through to keyword rules/default
    assert route("write me a poem", with_local, CFG, role="REVIEW") == "claude"
    # local harness down -> falls back to keyword rules/default, no error
    with_local["aider"]._ok = False
    assert route("write me a poem", with_local, CFG, role="IMPLEMENT") == "claude"
    # a local harness whose capabilities don't include "implement" is skipped
    caps_mismatch = _hs({"claude": True})
    caps_mismatch["aider"] = _AvailHarness("aider", True, kind="local", cost=0,
                                           capabilities=["docs"])
    assert route("write me a poem", caps_mismatch, CFG, role="IMPLEMENT") == "claude"

    print("router self-check ok")


if __name__ == "__main__":
    main()
