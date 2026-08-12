"""load_harnesses/profile self-check. Run: python test_harness.py"""
from omnigent.harness import Harness, load_harnesses

CFG = {
    "harnesses": {
        "claude": {"bin": "claude", "detect": "claude"},
        "codex": {"bin": "codex", "detect": "codex"},
        "aider": {"bin": "aider", "detect": "aider", "kind": "local", "cost": 0,
                  "capabilities": ["implement"]},
    },
    "profiles": {
        "default": ["claude", "codex", "aider"],
        "api": ["claude", "codex"],
        "local": ["aider"],
    },
}


def main():
    # no profile -> every harness (today's behavior), existing entries default to api/cost=1
    hs = load_harnesses(CFG)
    assert set(hs) == {"claude", "codex", "aider"}
    assert hs["claude"].kind == "api" and hs["claude"].cost == 1 and hs["claude"].capabilities == []
    assert hs["aider"].kind == "local" and hs["aider"].cost == 0
    assert isinstance(hs["claude"], Harness)

    # profile filters
    assert set(load_harnesses(CFG, profile="api")) == {"claude", "codex"}
    assert set(load_harnesses(CFG, profile="local")) == {"aider"}

    # unknown profile fails open -> all harnesses, never crashes
    assert set(load_harnesses(CFG, profile="nope")) == {"claude", "codex", "aider"}

    # uninstalled local agent (not on PATH) is unavailable, not an error
    assert hs["aider"].available is False
    assert hs["aider"].path is None

    print("harness/profile self-check ok")


if __name__ == "__main__":
    main()
