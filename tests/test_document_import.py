"""Local importer contracts: bounded parsing, durable provenance and retries."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from graph_engine.brain import Brain, Node
from graph_engine.brain_engine import BrainEngine
from graph_engine.document_import import chunk_text, import_documents
from graph_engine.embedder import HashEmbedder


@pytest.fixture
def brain(tmp_path, monkeypatch):
    monkeypatch.delenv("IG_ACCESS_POLICY", raising=False)
    return Brain(str(tmp_path / "brain"), mode="local")


def snapshot(brain):
    return {str(p.relative_to(brain.path)): p.read_bytes()
            for p in brain.path.rglob("*") if p.is_file() and ".git" not in p.parts}


def write(tmp_path, text="Alice works at Acme.", name="notes.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_unicode_locations_and_metadata_roundtrip(brain, tmp_path):
    text = "# Überblick\r\n\r\nGrüße 👋 — Über uns.\n\n## Deux\nBonjour 世界.\n"
    path = tmp_path / 'notes, [é].md'
    path.write_bytes(text.encode("utf-8"))
    result = import_documents(brain, [path], chunk_chars=25,
                              source_id='custom, [source]\n---\nid: hostile\u2028')
    file = result["files"][0]
    assert file["status"] == "complete" and len(file["chunks"]) > 1
    assert file["content_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    recovered = []
    for item in file["chunks"]:
        node = brain.read_node(item["node_id"])
        p = node.document
        raw = text[p["char_start"]:p["char_end"]]
        recovered.extend(c for c in raw if not c.isspace())
        assert node.capture["input"] == raw
        assert p["page"] is None
        assert len(raw) <= 25
        assert p["line_start"] == text.count("\n", 0, p["char_start"]) + 1
        assert p["line_end"] == text.count("\n", 0, p["char_end"]) + 1
        assert Node.from_markdown(node.to_markdown()).document == node.to_dict()["document"]
        assert node.id != "hostile"
    assert recovered == [c for c in text if not c.isspace()]
    assert file["source_id"] == 'custom, [source]\n---\nid: hostile\u2028'


@pytest.mark.parametrize("limit", [1, 2, 10, 40, 100])
def test_chunk_hard_bound_and_complete_non_whitespace(limit):
    text = "# Heading\n\n" + "abc世界" * 40 + "\n\n## Next\n" + "sentence words. " * 20
    chunks = chunk_text(text, limit)
    assert chunks == chunk_text(text, limit)
    assert all(0 < len(c.text) <= limit for c in chunks)
    assert "".join(c for ch in chunks for c in ch.text if not c.isspace()) == "".join(c for c in text if not c.isspace())


def test_paragraph_and_heading_boundaries():
    text = "# Heading\nParagraph one.\n\n## Next\nParagraph two."
    chunks = chunk_text(text, 35)
    assert chunks[0].text == "# Heading\nParagraph one."
    assert chunks[1].text == "## Next\nParagraph two."


def test_retry_is_noop_preserves_manual_edits_and_changed_versions(brain, tmp_path):
    path = write(tmp_path)
    first = import_documents(brain, [path], source_id="paper")
    nid = first["files"][0]["chunks"][0]["node_id"]
    before = snapshot(brain)
    retried = import_documents(brain, [path], source_id="paper")
    assert retried["created_chunks"] == 0 and retried["reused_chunks"] == 1
    assert snapshot(brain) == before
    node = brain.read_node(nid)
    node.text = "My manually corrected note."
    node.tags = ["curated"]
    brain.write_node(node)
    before = snapshot(brain)
    retry = import_documents(brain, [path], source_id="paper")
    assert retry["files"][0]["chunks"][0]["edited"]
    assert snapshot(brain) == before
    path.write_text("Alice works at Other.")
    changed = import_documents(brain, [path], source_id="paper")
    assert changed["created_chunks"] == 1 and len(brain.read_nodes()) == 2
    assert brain.read_node(nid).text == "My manually corrected note."
    path.write_text("Alice works at Acme.")
    assert import_documents(brain, [path], source_id="paper")["reused_chunks"] == 1
    assert len(brain.read_nodes()) == 2


def test_dry_run_never_initializes_syncs_embeds_or_calls_extractor(brain, tmp_path, monkeypatch):
    path = write(tmp_path)
    def fail(*args, **kwargs):
        raise AssertionError("write/model during dry run")
    for method in ("write_guard", "ensure_ready", "pull", "write_node", "write_vectors", "rebuild_index", "commit_and_push"):
        monkeypatch.setattr(brain, method, fail)
    monkeypatch.setattr("graph_engine.entities.command_extractor", fail)
    result = import_documents(brain, [path], dry_run=True, extraction="model")
    assert result["files"][0]["chunks"][0]["status"] == "planned"
    assert not brain.path.exists()


def test_dry_run_existing_git_brain_unchanged(tmp_path):
    brain = Brain(str(tmp_path / "brain"), mode="git")
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    path = write(tmp_path)
    # Set identity only for this fixture's repository.
    brain.ensure_ready()
    subprocess.run(["git", "-C", str(brain.path), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(brain.path), "commit", "-qm", "init"], check=True, env=env)
    before = {str(p.relative_to(brain.path)): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}
    assert import_documents(brain, [path], dry_run=True)["failed_files"] == 0
    assert {str(p.relative_to(brain.path)): p.read_bytes() for p in brain.path.rglob("*") if p.is_file()} == before


class SameVector(HashEmbedder):
    def embed(self, text):
        return [1., 0.]

    def embed_batch(self, texts):
        return [self.embed(t) for t in texts]


def test_semantic_duplicates_keep_each_source_exact_evidence(brain, tmp_path):
    engine = BrainEngine(brain, SameVector())
    original = engine.ingest("Alice works at OldCo.")[0]
    a = write(tmp_path, "Alice works at Acme.", "a.md")
    b = write(tmp_path, "Alice works at Other.", "b.md")
    result = import_documents(brain, [a, b], engine=engine, extraction="rules")
    assert result["failed_files"] == 0 and result["created_chunks"] == 2
    receipts = [f["chunks"][0] for f in result["files"]]
    assert all(c["duplicate"] and c["survivor_id"] == original.id for c in receipts)
    nodes = [brain.read_node(c["node_id"]) for c in receipts]
    assert nodes[0].document["source_id"] == a.resolve().as_uri()
    assert nodes[1].document["source_id"] == b.resolve().as_uri()
    assert {n.capture["input"] for n in nodes} == {a.read_text(), b.read_text()}
    facts = [e for e in brain.read_edges() if e.kind == "fact"]
    assert len(facts) == 2 and all(e.pending for e in facts)
    assert {e.evidence[0]["node_id"] for e in facts} == {n.id for n in nodes}
    assert brain.read_node(original.id).text == "Alice works at OldCo."
    before = snapshot(brain)
    retry = import_documents(brain, [a, b], engine=engine, extraction="rules")
    assert retry["created_chunks"] == 0 and retry["reused_chunks"] == 2
    assert snapshot(brain) == before
    assert engine.consolidate()["merged"] == 0
    assert all(brain.read_node(n.id).document == n.document for n in nodes)


def test_forget_and_retry_never_revives_receipts(brain, tmp_path):
    from graph_engine.agent_memory import forget
    engine = BrainEngine(brain, SameVector())
    original = engine.ingest("Original note")[0]
    path = write(tmp_path)
    imported = import_documents(brain, [path], engine=engine, extraction="rules")
    nid = imported["files"][0]["chunks"][0]["node_id"]
    forget(brain, original.id, reason="remove")
    before = snapshot(brain)
    retry = import_documents(brain, [path], engine=engine, extraction="rules")
    assert retry["created_chunks"] == 0 and retry["files"][0]["chunks"][0]["status"] == "tombstone"
    assert snapshot(brain) == before and brain.read_node(nid).status == "tombstone"


def test_selection_errors_limits_extensions_and_prefix(brain, tmp_path):
    directory = tmp_path / "documents"
    directory.mkdir()
    write(directory, name="a.md")
    write(directory, name="b.txt")
    write(directory, name="c.csv")
    (directory / "nested").mkdir()
    write(directory / "nested", name="d.md")
    result = import_documents(brain, [directory], extensions=["md"], source_prefix="library", recursive=True)
    assert result["created_chunks"] == 2
    assert {f["source_id"] for f in result["files"] if "source_id" in f} == {"library/a.md", "library/nested/d.md"}
    assert sum(f["status"] == "skipped" for f in result["files"]) == 2
    result = import_documents(brain, [tmp_path / "absent", directory / "b.txt"], max_bytes=2)
    assert result["failed_files"] == 2
    assert {f["error"] for f in result["files"]} == {"missing_path", "file_too_large"}
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe")
    assert import_documents(brain, [bad])["files"][0]["error"] == "invalid_utf8"
    with pytest.raises(ValueError):
        import_documents(brain, [directory], source_id="one")
    with pytest.raises(ValueError):
        import_documents(brain, [bad], extensions=["exe"])
    missing = import_documents(brain, [tmp_path / "absent"], source_id="missing-doc")
    assert missing["files"][0]["error"] == "missing_path"


def test_symlinks_fifos_and_unreadable_files_reported(brain, tmp_path, monkeypatch):
    directory = tmp_path / "docs"
    directory.mkdir()
    path = write(directory)
    (directory / "alias.md").symlink_to(path)
    (directory / "cycle").symlink_to(directory, target_is_directory=True)
    os.mkfifo(directory / "pipe.txt")
    original_open = os.open
    def denied(path_arg, *args, **kwargs):
        if Path(path_arg) == path:
            raise PermissionError("file is unreadable")
        return original_open(path_arg, *args, **kwargs)
    monkeypatch.setattr(os, "open", denied)
    result = import_documents(brain, [directory], recursive=True)
    assert result["failed_files"] == 4
    assert {f["error"] for f in result["files"]} == {"symbolic_link", "not_regular_file", "access_denied"}
    assert not brain.path.exists()


def test_discovery_limit_fails_before_writes(brain, tmp_path, monkeypatch):
    monkeypatch.setattr("graph_engine.document_import.MAX_FILES", 2)
    for i in range(3):
        write(tmp_path, name=f"{i}.md")
    with pytest.raises(ValueError, match="Selection exceeds"):
        import_documents(brain, [tmp_path])
    assert not brain.path.exists()


def test_partial_commit_failure_is_retryable_without_duplicate_or_edit_loss(brain, tmp_path, monkeypatch):
    path = write(tmp_path)
    original_commit = brain.commit_and_push
    def fail(*args, **kwargs):
        raise RuntimeError("commit failed")
    monkeypatch.setattr(brain, "commit_and_push", fail)
    assert import_documents(brain, [path])["failed_files"] == 1
    assert len(brain.read_nodes()) == 1
    monkeypatch.setattr(brain, "commit_and_push", original_commit)
    result = import_documents(brain, [path])
    assert result["failed_files"] == 0 and result["reused_chunks"] == 1
    assert len(brain.read_nodes()) == 1


def test_failed_model_extraction_can_retry_without_recapture(brain, tmp_path, monkeypatch):
    from graph_engine.entities import rule_extract
    path = write(tmp_path)
    engine = BrainEngine(brain, HashEmbedder())
    def failure(text):
        raise RuntimeError("private adapter detail")
    monkeypatch.setattr("graph_engine.entities.command_extractor", lambda: failure)
    first = import_documents(brain, [path], engine=engine, extraction="model")
    assert first["failed_files"] == 1 and first["created_chunks"] == 1
    assert first["files"][0]["status"] == "partial"
    assert "private adapter detail" not in json.dumps(first)
    nid = first["files"][0]["chunks"][0]["node_id"]
    monkeypatch.setattr("graph_engine.entities.command_extractor", lambda: rule_extract)
    second = import_documents(brain, [path], engine=engine, extraction="model")
    assert second["failed_files"] == 0 and second["reused_chunks"] == 1
    assert second["files"][0]["chunks"][0]["node_id"] == nid
    assert second["files"][0]["chunks"][0]["extraction"]["created_facts"] == 1


def make_pdf(path, *, encrypted=False, blank=False):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = pypdf.PdfWriter()
    for text in ("First page paragraph.", "Second page evidence."):
        page = writer.add_blank_page(width=300, height=300)
        if not blank:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
                DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("password")
    with path.open("wb") as stream:
        writer.write(stream)


def test_multipage_pdf_provenance_and_repeat(brain, tmp_path):
    path = tmp_path / "paper.pdf"
    make_pdf(path)
    result = import_documents(brain, [path], extensions=["pdf"], source_id="paper")
    assert result["failed_files"] == 0 and result["created_chunks"] == 2
    nodes = [brain.read_node(c["node_id"]) for c in result["files"][0]["chunks"]]
    assert [n.document["page"] for n in nodes] == [1, 2]
    assert [n.document["chunk_index"] for n in nodes] == [1, 2]
    assert "First page" in nodes[0].text and "Second page" in nodes[1].text
    before = snapshot(brain)
    assert import_documents(brain, [path], extensions=["pdf"], source_id="paper")["reused_chunks"] == 2
    assert snapshot(brain) == before


def test_pdf_malformed_encrypted_blank_and_limits(brain, tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    encrypted, broken, blank = [tmp_path / f"{s}.pdf" for s in ("encrypted", "broken", "blank")]
    make_pdf(encrypted, encrypted=True)
    broken.write_bytes(b"not a pdf")
    make_pdf(blank, blank=True)
    result = import_documents(brain, [encrypted, broken, blank], extensions=["pdf"])
    assert result["failed_files"] == 2
    assert {f.get("error") for f in result["files"]} == {None, "encrypted_pdf", "malformed_pdf"}
    assert not brain.path.exists()
    path = tmp_path / "limit.pdf"
    make_pdf(path)
    monkeypatch.setattr("graph_engine.document_import.MAX_PAGES", 1)
    assert import_documents(brain, [path], extensions=["pdf"])["files"][0]["error"] == "too_many_pages"
    monkeypatch.setattr("graph_engine.document_import.MAX_PAGES", 1000)
    monkeypatch.setattr("graph_engine.document_import.MAX_TEXT_CHARS", 5)
    assert import_documents(brain, [path], extensions=["pdf"])["files"][0]["error"] == "extracted_text_too_large"
    assert not brain.path.exists()


def test_pdf_missing_extra_is_actionable(brain, tmp_path, monkeypatch):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.7")
    monkeypatch.setitem(sys.modules, "pypdf", None)
    result = import_documents(brain, [path], extensions=["pdf"])
    assert result["files"][0]["error"] == "pdf_extra_missing"
    assert "[pdf]" in result["files"][0]["message"]
    assert not brain.path.exists()


def test_cli_basic_and_dry_run_skip_engine(brain, tmp_path, monkeypatch, capsys):
    from graph_engine import __main__ as cli
    path = write(tmp_path)
    monkeypatch.setattr(cli.runtime, "make_brain", lambda: brain)
    def forbidden():
        raise AssertionError("basic import must not load embedder")
    monkeypatch.setattr(cli.runtime, "make_engine", forbidden)
    monkeypatch.setattr(sys, "argv", ["ig", "import", str(path), "--dry-run", "--extract-model", "--json"])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] and not brain.path.exists()
    monkeypatch.setattr(sys, "argv", ["ig", "import", str(path), "--source-id", "private-label", "--json"])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["created_chunks"] == 1
    assert brain.read_nodes()[0].document["source_id"] == "private-label"
    with pytest.raises(SystemExit) as exc:
        cli.cmd_import([str(tmp_path / "missing"), "--json"])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["failed_files"] == 1


def test_protected_import_acl_and_duplicate_inheritance(brain, tmp_path, monkeypatch):
    from graph_engine.access import SecuredBrain
    policy_path = tmp_path / "policy.json"
    policy = {"graphs": {"default": {"roles": {"owner": "admin", "alice": "editor", "bob": "viewer"}}}}
    policy_path.write_text(json.dumps(policy))
    monkeypatch.setenv("IG_ACCESS_POLICY", str(policy_path))
    path = write(tmp_path)
    viewer = SecuredBrain(str(brain.path), mode="local", graph_name="default", identity="bob")
    assert import_documents(viewer, [path], dry_run=True)["failed_files"] == 0
    with pytest.raises(PermissionError):
        import_documents(viewer, [path])
    editor = SecuredBrain(str(brain.path), mode="local", graph_name="default", identity="alice")
    engine = BrainEngine(editor, SameVector())
    survivor = engine.ingest("Old claim")[0]
    result = import_documents(editor, [path], engine=engine, extraction="rules")
    nid = result["files"][0]["chunks"][0]["node_id"]
    policy["graphs"]["default"]["nodes"] = {survivor.id: {"read": ["owner"], "write": ["owner"]}}
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(PermissionError):
        editor.read_node(nid)
    before = snapshot(brain)
    retried = import_documents(editor, [path], engine=engine, extraction="rules")
    assert retried["failed_files"] == 1 and retried["files"][0]["error"] == "access_denied"
    assert snapshot(brain) == before
    assert editor.read_edges() == []


@pytest.mark.parametrize("invalid", [True, False])
def test_edited_receipt_metadata_or_broken_record_never_overwritten(brain, tmp_path, invalid):
    path = write(tmp_path)
    result = import_documents(brain, [path])
    nid = result["files"][0]["chunks"][0]["node_id"]
    if invalid:
        brain.node_path(nid).write_text("My manual note without frontmatter")
    else:
        node = brain.read_node(nid)
        node.document["source_id"] = "another-source"
        brain.write_node(node)
    before = snapshot(brain)
    repeated = import_documents(brain, [path])
    assert repeated["failed_files"] == 1
    assert repeated["files"][0]["error"] == ("receipt_unreadable" if invalid else "receipt_conflict")
    assert snapshot(brain) == before


def test_concurrent_process_import_reuses_one_git_receipt(tmp_path):
    source = write(tmp_path)
    brain_path = tmp_path / "brain"
    script = """
import json, sys
from graph_engine.brain import Brain
from graph_engine.document_import import import_documents
result = import_documents(Brain(sys.argv[1], mode='git'), [sys.argv[2]], source_id='shared')
print(json.dumps(result))
"""
    processes = [subprocess.Popen([sys.executable, "-c", script, str(brain_path), str(source)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(2)]
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        results.append(json.loads(stdout))
    assert sum(r["created_chunks"] for r in results) == 1
    assert sum(r["reused_chunks"] for r in results) == 1
    assert all(r["failed_files"] == 0 for r in results)
    brain = Brain(str(brain_path), mode="git")
    assert len(brain.read_nodes()) == 1
    status = subprocess.run(["git", "-C", str(brain_path), "status", "--porcelain"],
                            capture_output=True, text=True, check=True)
    assert not status.stdout
    subprocess.run(["git", "-C", str(brain_path), "fsck", "--no-dangling"], check=True, capture_output=True)


def test_import_provenance_visible_in_http(brain, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from graph_engine import runtime
    from graph_engine.server import app
    path = write(tmp_path)
    result = import_documents(brain, [path], source_id="public-paper")
    nid = result["files"][0]["chunks"][0]["node_id"]
    monkeypatch.delenv("IG_GRAPH_HOME", raising=False)
    monkeypatch.setenv("IG_BRAIN_PATH", str(brain.path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    runtime.reset_engine_cache()
    before = snapshot(brain)
    nodes = TestClient(app).get("/api/graph").json()["nodes"]
    assert next(n for n in nodes if n["id"] == nid)["document"]["source_id"] == "public-paper"
    assert snapshot(brain) == before
