"""Knowledge (RAG) self-check — temp vault, FTS5 index, incremental sync, graceful
degrade, safe writer, and the workflow hook (context injected + memory written).
Run: python test_knowledge.py
"""
import subprocess
import tempfile
from pathlib import Path

from omnigent.knowledge.config import KnowledgeConfig, SourceCfg
from omnigent.knowledge.service import KnowledgeService
from omnigent.knowledge.types import MemoryRecord
from omnigent.knowledge.writer import ObsidianWriter
from omnigent.workflow.models import Store
from omnigent.workflow.service import WorkflowService


def _vault() -> Path:
    v = Path(tempfile.mkdtemp(prefix="omni_vault_"))
    d = v / "Projects" / "TestApp" / "Decisions"
    d.mkdir(parents=True)
    (d / "Auth.md").write_text(
        "---\nkind: decision\nstatus: active\n---\n"
        "# Authentication\nUse server-side sessions. Refresh tokens must remain server-side.\n",
        encoding="utf-8")
    (v / "Projects" / "TestApp" / "Notes.md").write_text(
        "---\nstatus: deprecated\n---\n# Old\nWe used JWT in localStorage (deprecated).\n",
        encoding="utf-8")
    return v


def _svc(vault: Path, db: Path) -> KnowledgeService:
    cfg = KnowledgeConfig(enabled=True, sources=[
        SourceCfg(name="main", type="obsidian", path=str(vault),
                  include=["**/*.md"], exclude=[".obsidian/**"])])
    return KnowledgeService.load(cfg, db_path=db)


def test_index_search():
    tmp = Path(tempfile.mkdtemp(prefix="omni_k_"))
    vault = _vault()
    ks = _svc(vault, tmp / "knowledge.db")
    n = ks.sync()
    assert n["indexed"] >= 2, n
    hits = ks.search("refresh token session")
    assert hits and any("Auth.md" in h.uri for h in hits), hits
    assert all("Notes.md" not in h.uri for h in hits), "deprecated note must be excluded by default"
    n2 = ks.sync()
    assert n2["indexed"] == 0 and n2["skipped"] >= 2, n2       # incremental: unchanged skipped
    (vault / "Projects" / "TestApp" / "Decisions" / "Auth.md").write_text(
        "---\nkind: decision\n---\n# Auth\nServer-side sessions; rotate refresh tokens.\n",
        encoding="utf-8")
    n3 = ks.sync()
    assert n3["indexed"] == 1, n3                              # changed → reindexed
    print("index/search ok:", n, "->", n3)


def test_degrade():
    tmp = Path(tempfile.mkdtemp(prefix="omni_k_"))
    ks = _svc(Path("Z:/nonexistent-vault-xyz"), tmp / "k.db")
    ks.sync()                                                  # must not raise
    assert ks.search("anything") == []
    ctx, prov = ks.context_for_task({"title": "x", "acceptance_criteria": []}, project="none")
    assert ctx == "" and prov == []
    print("degrade ok")


def test_writer_guard():
    tmp = Path(tempfile.mkdtemp(prefix="omni_k_"))
    vault = _vault()
    ks = _svc(vault, tmp / "k.db")
    rec = MemoryRecord(kind="run-summary", project="testapp", title="Run Guard",
                       body="# Result\nDid the thing.\n", run_id="r1")
    target = ObsidianWriter(str(vault))._path(rec)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# a human note, not omni-managed\n", encoding="utf-8")
    assert ks.write_memory(rec) is None, "must refuse to overwrite a human note"
    target.write_text("---\nomni_managed: true\n---\nold\n", encoding="utf-8")
    uri = ks.write_memory(rec)
    assert uri and "_Omni" in uri, "must write over an omni-managed note"
    print("writer guard ok")


def test_workflow_with_knowledge():
    tmp = Path(tempfile.mkdtemp(prefix="omni_kw_"))
    vault = _vault()
    repo = tmp / "repo"; repo.mkdir()

    def g(*a):
        p = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        return p.stdout
    g("init", "-q"); g("config", "user.email", "t@t.dev"); g("config", "user.name", "T")
    (repo / "README.md").write_text("readme"); g("add", "-A"); g("commit", "-q", "-m", "init")
    base = g("rev-parse", "--abbrev-ref", "HEAD").strip()

    ks = _svc(vault, tmp / "k.db"); ks.sync()
    svc = WorkflowService(store=Store(tmp / "omni.db"), mock=True, knowledge=ks)
    proj = svc.create_project("TestApp", str(repo), default_branch=base)
    run = svc.create_run(proj["id"], "Add auth callback")
    svc.create_task(run["id"], "Implement OAuth callback", agent="claude",
                    acceptance_criteria=["refresh token stays server-side"])
    svc.drive(run["id"])
    ev = lambda: {e["event_type"] for e in svc.store.query("run_events", "run_id=?", (run["id"],))}
    assert "CONTEXT_RETRIEVED" in ev(), ev()
    svc.approve_run(run["id"])
    assert "MEMORY_WRITTEN" in ev(), ev()
    mem = list((vault / "_Omni").rglob("*.md"))
    assert mem, "expected a run-summary note under _Omni"
    print("workflow+knowledge ok: context injected, memory written ->", mem[0].name)


if __name__ == "__main__":
    test_index_search()
    test_degrade()
    test_writer_guard()
    test_workflow_with_knowledge()
    print("knowledge self-check ok")
