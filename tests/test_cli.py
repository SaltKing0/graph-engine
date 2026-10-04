"""CLI dispatch + usage-error tests (audit #57: the dispatch surface had zero tests).

Every test runs the real CLI in a subprocess against a temp brain, so the
full dispatch path (argv -> COMMANDS -> cmd_* -> engine) is exercised.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
# sys.executable = the interpreter running pytest: the repo venv locally, the
# CI environment on GitHub Actions (where no .venv exists).
PY = sys.executable


def run_cli(args: list[str], tmp_path, env_extra: dict | None = None,
            stdin: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ,
               IG_BRAIN_MODE="local",
               IG_BRAIN_PATH=str(tmp_path / "brain"),
               IDEAGRAPH_EMBEDDER="hash",
               PYTHONPATH=str(REPO))
    if env_extra:
        env.update(env_extra)
    return subprocess.run([PY, "-m", "graph_engine", *args],
                          capture_output=True, text=True, env=env,
                          input=stdin, timeout=120)


def test_help_exits_zero(tmp_path):
    r = run_cli(["--help"], tmp_path)
    assert r.returncode == 0
    assert "graph_engine init" in r.stdout
    assert "graph_engine consolidate" in r.stdout


def test_unknown_command_exits_one_with_message(tmp_path):
    r = run_cli(["definitely-not-a-command"], tmp_path)
    assert r.returncode == 1
    assert "Unknown command" in r.stdout
    assert "definitely-not-a-command" in r.stdout
    assert "Traceback" not in r.stderr


def test_init_creates_brain_and_second_init_fails_cleanly(tmp_path):
    r = run_cli(["init"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "brain" / "nodes").is_dir()
    # non-empty dir -> friendly error, no traceback
    r2 = run_cli(["init"], tmp_path)
    assert r2.returncode == 1
    assert "already contains a brain" in r2.stdout
    assert "Traceback" not in r2.stderr


def test_ingest_and_search_roundtrip(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["ingest", "Cats hunt mice at night", "--source", "test"], tmp_path)
    assert r.returncode == 0, r.stderr
    r = run_cli(["search", "cats"], tmp_path)
    assert r.returncode == 0
    assert "hits (hybrid dense+BM25)" in r.stdout


def test_ingest_stdin_marker(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["ingest", "-"], tmp_path, stdin="Owls hunt mice at night\n")
    assert r.returncode == 0, r.stderr
    r2 = run_cli(["search", "owls"], tmp_path)
    assert "1 hits" in r2.stdout or "hits" in r2.stdout


def test_ingest_stdin_rejects_mixed_args(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["ingest", "-", "extra"], tmp_path, stdin="text\n")
    assert r.returncode == 1
    assert "cannot be combined" in r.stdout
    assert "Traceback" not in r.stderr


def test_ingest_missing_source_is_usage_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["ingest", "some text", "--source"], tmp_path)
    assert r.returncode == 1
    assert "Usage" in r.stdout
    assert "Traceback" not in r.stderr


def test_accept_missing_arg_is_usage_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["accept"], tmp_path)
    assert r.returncode == 1
    assert "Usage" in r.stdout
    assert "Traceback" not in r.stderr


def test_accept_unknown_edge_clean_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["accept", "deadbeef1234"], tmp_path)
    assert r.returncode == 1
    assert "not found or not pending" in r.stdout


def test_gaps_bad_min_is_usage_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["gaps", "--min", "abc"], tmp_path)
    assert r.returncode == 1
    assert "expects a number" in r.stdout
    assert "Traceback" not in r.stderr


def test_near_dup_invalid_band_is_usage_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["near-dup", "--lo", "2", "--hi", "1"], tmp_path)
    assert r.returncode == 1
    assert "must be smaller" in r.stdout


def test_near_dup_max_zero_means_zero(tmp_path):
    """#26 semantics: --max 0 limits to 0 pairs, it does not disable the limit."""
    assert run_cli(["init", "--demo"], tmp_path).returncode == 0
    r = run_cli(["near-dup", "--max", "0", "--json"], tmp_path)
    assert r.returncode == 0
    assert r.stdout.strip() == "[]"


def test_ig_brain_path_expanduser(tmp_path, monkeypatch):
    """#33: an explicit IG_BRAIN_PATH with ~ is expanded, not written literally."""
    r = run_cli(["status"], tmp_path, env_extra={"IG_BRAIN_PATH": "~/ig-test-expand-9182"})
    # status on a missing brain must fail cleanly (no crash), and NO literal ./~ dir
    # was created in the CWD
    assert "Traceback" not in r.stderr
    home = Path(os.path.expanduser("~"))
    created = home / "ig-test-expand-9182"
    # status creates nothing on a missing brain — but if it did, it would be expanded
    assert not (Path.cwd() / "~").exists()
    if created.exists():
        import shutil
        shutil.rmtree(created)


def test_status_on_missing_brain_clean_error(tmp_path):
    r = run_cli(["status"], tmp_path)
    assert "Traceback" not in r.stderr
    # either a friendly message or a non-zero exit — never a traceback
    assert r.returncode != 0 or "Status" in r.stdout


def test_search_without_args_is_usage(tmp_path):
    r = run_cli(["search"], tmp_path)
    assert r.returncode == 1
    assert "Usage: ig search <term>" in r.stdout


def test_explain_roundtrip_and_no_file_changes(tmp_path):
    import json
    from graph_engine.brain import Brain, Edge, Node

    brain = Brain(tmp_path / "brain", mode="local")
    brain.ensure_ready()
    brain.write_node(Node(id="a", text="alpha beta"))
    brain.write_node(Node(id="b", text="alpha gamma"))
    # Legacy edge without origin exercises the text formatter too.
    brain.write_edges([Edge(source="a", target="b", kind="extends", pending=False)])
    before = {p: p.read_bytes() for p in brain.path.rglob("*") if p.is_file()}
    r = run_cli(["explain", "a", "--query", "alpha", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["retrieved"] and data["matched_terms"] == ["alpha"]
    assert len(data["graph_context"]) == 1
    r = run_cli(["explain", "a", "--query", "alpha"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "RRF contribution=" in r.stdout
    assert "context only; not used for ranking" in r.stdout
    assert {p: p.read_bytes() for p in brain.path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("args", [[], ["a"], ["a", "--query", "alpha", "--top", "bad"],
                                 ["a", "--query", "alpha", "--unknown"]])
def test_explain_usage_errors(tmp_path, args):
    r = run_cli(["explain", *args], tmp_path)
    assert r.returncode != 0
    assert "usage: ig explain" in r.stderr
    assert "Traceback" not in r.stderr


def test_explain_unknown_node_clean_error(tmp_path):
    r = run_cli(["explain", "missing", "--query", "alpha"], tmp_path)
    assert r.returncode == 1
    assert "No node" in r.stdout
    assert "Traceback" not in r.stderr


def test_search_json_emits_machine_readable_shape(tmp_path):
    """`ig search --json` is the machine-readable mode the MCP handoff asked for:
    stdout carries ONLY the JSON payload (the ST-fallback notice must stay on
    stderr — a polluted stdout breaks `ig search --json | jq`)."""
    r = run_cli(["ingest", "Vector databases store embeddings for RAG retrieval"], tmp_path)
    assert r.returncode == 0
    r = run_cli(["search", "vector databases", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr
    import json
    data = json.loads(r.stdout)  # raises if stdout is not pure JSON
    assert data["count"] >= 1
    top = data["results"][0]
    assert {"id", "score", "snippet", "status", "type", "tags", "created"} <= set(top)
    assert 0.0 <= top["score"]

def test_search_json_empty_result_is_valid_json(tmp_path):
    run_cli(["ingest", "Completely unrelated anchovy pizza history"], tmp_path)
    r = run_cli(["search", "zzzqqqxxx nonexistent term", "--json"], tmp_path)
    assert r.returncode == 0
    import json
    data = json.loads(r.stdout)
    assert data["count"] == 0 and data["results"] == []

def test_search_text_mode_unchanged(tmp_path):
    run_cli(["ingest", "Vector databases store embeddings for RAG retrieval"], tmp_path)
    r = run_cli(["search", "vector databases"], tmp_path)
    assert r.returncode == 0
    assert "hits (hybrid dense+BM25)" in r.stdout

def test_search_usage_error_mentions_json(tmp_path):
    r = run_cli(["search"], tmp_path)
    assert r.returncode == 1
    assert "Usage: ig search <term> [--json]" in r.stdout

# ---------------------------------------------------------------------------
# ig communities (report #3): read-only topology report
# ---------------------------------------------------------------------------

def test_communities_missing_brain_clean_error(tmp_path):
    # Family behavior (mirrors test_status_on_missing_brain_clean_error):
    # either a friendly message / empty report or a non-zero exit — never a
    # traceback. The engine auto-creates an empty local-mode brain, so the
    # honest output is a clean empty report.
    r = run_cli(["communities"], tmp_path)
    assert "Traceback" not in r.stdout + r.stderr
    assert r.returncode != 0 or "Communities (0 nodes" in r.stdout


def test_communities_bad_numeric_usage_error(tmp_path):
    r = run_cli(["ingest", "alpha beta gamma delta knowledge"], tmp_path)
    assert r.returncode == 0
    r = run_cli(["communities", "--min-size", "abc"], tmp_path)
    assert r.returncode == 1
    assert "Traceback" not in r.stdout
    assert "--min-size expects a number" in r.stdout
    r = run_cli(["communities", "--top", "xyz"], tmp_path)
    assert r.returncode == 1
    assert "--top expects a number" in r.stdout
    r = run_cli(["communities", "--betweenness-sample", "pi"], tmp_path)
    assert r.returncode == 1
    assert "--betweenness-sample expects a number" in r.stdout


def test_communities_json_shape(tmp_path):
    run_cli(["ingest", "alpha beta gamma delta knowledge"], tmp_path)
    r = run_cli(["communities", "--min-size", "1", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    import json
    data = json.loads(r.stdout)
    for key in ("nodes", "edges", "modularity", "betweenness_sample",
                "communities", "god_nodes", "gaps", "isolated"):
        assert key in data, f"missing key {key}"
    assert data["nodes"] >= 1


def test_communities_top_zero_json_empty_gaps(tmp_path):
    run_cli(["ingest", "alpha beta gamma delta knowledge"], tmp_path)
    r = run_cli(["communities", "--min-size", "1", "--top", "0", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    import json
    data = json.loads(r.stdout)
    assert data["gaps"] == []


def test_communities_human_report_mentions_sections(tmp_path):
    run_cli(["ingest", "alpha beta gamma delta knowledge"], tmp_path)
    r = run_cli(["communities", "--min-size", "1"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Communities (" in r.stdout
    assert "God nodes" in r.stdout

# ---------------------------------------------------------------------------
# ig report (report #7): one-page state-of-the-brain digest
# ---------------------------------------------------------------------------

def test_report_renders_digest(tmp_path):
    run_cli(["ingest", "Die Erde ist eine Scheibe"], tmp_path)
    run_cli(["ingest", "Die Erde ist keine Scheibe"], tmp_path)
    r = run_cli(["report"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "# BRAIN_REPORT" in r.stdout
    assert "## Intent review queue" in r.stdout
    assert "contradicts" in r.stdout


def test_report_json_parses(tmp_path):
    run_cli(["ingest", "Die Erde ist eine Scheibe"], tmp_path)
    r = run_cli(["report", "--json"], tmp_path)
    assert r.returncode == 0, r.stderr
    import json
    data = json.loads(r.stdout)
    assert {"generated_at", "nodes", "edges", "kinds", "intent_queue"} <= set(data)


def test_report_bad_since_usage_error(tmp_path):
    r = run_cli(["report", "--since", "not-a-date-or-hours"], tmp_path)
    assert r.returncode == 1
    assert "Traceback" not in r.stdout
    assert "--since expects" in r.stdout


def test_report_empty_brain_clean(tmp_path):
    r = run_cli(["report"], tmp_path)
    assert r.returncode == 0
    assert "# BRAIN_REPORT" in r.stdout
    assert "0 nodes / 0 live edges" in r.stdout

def test_report_write_local_mode_no_commit(tmp_path):
    run_cli(["ingest", "Die Erde ist eine Scheibe"], tmp_path)
    r = run_cli(["report", "--write"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "written: BRAIN_REPORT.md (local mode, no commit)" in r.stdout
    f = tmp_path / "brain" / "BRAIN_REPORT.md"
    assert f.exists()
    assert "# BRAIN_REPORT" in f.read_text(encoding="utf-8")


def _seed_consolidation(tmp_path, *, recall_count=0):
    from graph_engine.brain import Brain, Node
    brain = Brain(tmp_path / "brain", mode="local")
    brain.write_node(Node(id="event", text="User prefers concise responses",
                          ntype="episodic", status="active", recall_count=recall_count,
                          created="2020-01-01T00:00:00Z"))
    return brain


def test_consolidate_cli_env_overrides_preview_and_repeat(tmp_path):
    import json
    brain = _seed_consolidation(tmp_path)
    env = {"IG_CONSOLIDATE_THRESHOLD": "99", "IG_CONSOLIDATE_MIN_AGE_DAYS": "0"}
    before = brain.node_path("event").read_bytes()
    blocked = run_cli(["consolidate", "--json"], tmp_path, env)
    assert blocked.returncode == 0, blocked.stderr
    assert json.loads(blocked.stdout)["candidates"] == []
    preview = run_cli(["consolidate", "--threshold", "0", "--dry-run", "--json"], tmp_path, env)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["candidates"] == ["event"]
    assert len(brain.read_nodes()) == 1
    real = run_cli(["consolidate", "--threshold", "0", "--json"], tmp_path, env)
    assert real.returncode == 0, real.stderr
    assert json.loads(real.stdout)["created"] == 1
    assert brain.node_path("event").read_bytes() == before
    again = run_cli(["consolidate", "--threshold", "0", "--json"], tmp_path, env)
    assert json.loads(again.stdout)["edges"] == 0


def test_dream_plan_and_consolidation_json(tmp_path):
    import json
    brain = _seed_consolidation(tmp_path)
    plan = run_cli(["dream", "--threshold", "0", "--json"], tmp_path)
    assert plan.returncode == 0, plan.stderr
    assert json.loads(plan.stdout)["consolidation"]["candidates"] == ["event"]
    assert len(brain.read_nodes()) == 1
    result = run_cli(["dream", "--consolidate", "--threshold", "0",
                      "--consolidate-limit", "1", "--json"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["consolidation"]["created"] == 1


def test_dream_refresh_folds_recall_before_extracting(tmp_path):
    import json
    from graph_engine.recall import record
    brain = _seed_consolidation(tmp_path)
    record(brain, "preferences", ["event"])
    result = run_cli(["dream", "--refresh", "--consolidate", "--json"], tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["refresh"]["recalls"] == 1
    assert data["consolidation"]["created"] == 1


@pytest.mark.parametrize("command", ["consolidate", "dream"])
@pytest.mark.parametrize("option,value", [
    ("--threshold", "-1"), ("--min-age-days", "nan"),
    ("--min-count", "0"), ("--threshold", "words"),
])
def test_consolidation_invalid_flags_abort_before_writes(tmp_path, command, option, value):
    brain = _seed_consolidation(tmp_path)
    args = [command]
    if command == "dream":
        args += ["--refresh", "--consolidate"]
    result = run_cli(args + [option, value], tmp_path)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert len(brain.read_nodes()) == 1
    assert not (brain.path / "INDEX.md").exists()  # refresh never ran


def test_dream_missing_consolidation_gate_value_is_usage_error(tmp_path):
    result = run_cli(["dream", "--consolidate", "--threshold"], tmp_path)
    assert result.returncode == 1
    assert "Usage" in result.stdout and "Traceback" not in result.stderr


@pytest.mark.parametrize("command", [["consolidate"], ["dream", "--consolidate"]])
def test_consolidation_llm_is_separate_from_dream_summarizer(tmp_path, command):
    import json
    brain = _seed_consolidation(tmp_path, recall_count=1)
    result = run_cli(command + ["--llm", "--json"], tmp_path, {
        "IG_CONSOLIDATE_LLM_CMD": "printf 'Prefers concise answers'",
        "IG_DREAM_LLM_CMD": "",
    })
    assert result.returncode == 0, result.stderr
    assert next(n.text for n in brain.read_nodes() if n.ntype == "semantic") == "Prefers concise answers"
    assert json.loads(result.stdout)


def test_consolidation_llm_failure_or_preview_never_writes(tmp_path):
    import json
    brain = _seed_consolidation(tmp_path, recall_count=1)
    env = {"IG_CONSOLIDATE_LLM_CMD": "exit 7"}
    preview = run_cli(["consolidate", "--llm", "--dry-run", "--json"], tmp_path, env)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["candidates"] == ["event"]
    real = run_cli(["consolidate", "--llm"], tmp_path, env)
    assert real.returncode == 1
    assert "failed (7)" in real.stderr and "Traceback" not in real.stderr
    assert len(brain.read_nodes()) == 1


def test_consolidation_llm_empty_output_declines(tmp_path):
    import json
    brain = _seed_consolidation(tmp_path, recall_count=1)
    result = run_cli(["consolidate", "--llm", "--json"], tmp_path,
                     {"IG_CONSOLIDATE_LLM_CMD": "true"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["skipped"] == 1
    assert len(brain.read_nodes()) == 1


def test_consolidation_llm_requires_configured_command(tmp_path):
    result = run_cli(["consolidate", "--llm"], tmp_path,
                     {"IG_CONSOLIDATE_LLM_CMD": ""})
    assert result.returncode == 1
    assert "IG_CONSOLIDATE_LLM_CMD" in result.stdout
    assert "Traceback" not in result.stderr


# Entity/fact extraction: CLI parsing and persisted graph across processes.
def test_entities_cli_preview_stdin_and_alias_linking(tmp_path):
    import json
    from graph_engine.brain import Brain
    preview = run_cli(["entities", "Alice works at Acme.", "--dry-run", "--json"], tmp_path)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["created_entities"] == 2
    assert not (tmp_path / "brain").exists()
    first = run_cli(["entities", "-", "--json"], tmp_path,
                    stdin="Alice works at International Business Machines (IBM).\n")
    assert first.returncode == 0, first.stderr
    second = run_cli(["entities", "Alice founded IBM.", "--json", "--accept-facts"], tmp_path)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["created_entities"] == 0
    assert not json.loads(second.stdout)["facts"][0]["pending"]
    brain = Brain(tmp_path / "brain", mode="local")
    assert len([n for n in brain.read_nodes() if n.ntype == "entity"]) == 2
    human = run_cli(["entities", "Alice founded IBM."], tmp_path)
    assert "--[founded]-->" in human.stdout and "(accepted)" in human.stdout


def test_entities_cli_existing_source_and_clean_failure(tmp_path):
    import json
    from graph_engine.brain import Brain, Node
    brain = Brain(tmp_path / "brain", mode="local")
    node = Node("Alice works at Acme.", id="episode", ntype="episodic")
    brain.write_node(node)
    result = run_cli(["entities", "--node", "episode", "--json"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["source_node_id"] == "episode"
    missing = run_cli(["entities", "--node", "missing"], tmp_path)
    assert missing.returncode == 1 and "source node" in missing.stderr
    assert "Traceback" not in missing.stderr


@pytest.mark.parametrize("args", [[], ["--node"], ["text", "--node", "id"],
                                 ["text", "--source"], ["text", "--unknown"], ["-", "extra"]])
def test_entities_cli_usage_errors(tmp_path, args):
    result = run_cli(["entities", *args], tmp_path)
    assert result.returncode != 0 and "usage: ig entities" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "brain").exists()


def test_entities_cli_llm_errors_and_preview(tmp_path):
    import json
    for command in ("", "exit 7", "printf invalid"):
        result = run_cli(["entities", "Alice works at Acme", "--llm"], tmp_path,
                         {"IG_ENTITIES_LLM_CMD": command})
        assert result.returncode == 1 and "IG_ENTITIES_LLM_CMD" in result.stderr
        assert "Traceback" not in result.stderr
    result = run_cli(["entities", "Alice works at Acme", "--llm", "--dry-run", "--json"], tmp_path,
                     {"IG_ENTITIES_LLM_CMD": 'printf \'{"entities":[],"facts":[]}\''})
    assert result.returncode == 0, result.stderr
    assert not json.loads(result.stdout)["changed"]
    assert not list((tmp_path / "brain").rglob("*.md"))


def test_entities_cli_review_shows_directed_predicate_and_evidence(tmp_path):
    import json
    result = run_cli(["entities", "Alice works at Acme.", "--json"], tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    pending = run_cli(["pending"], tmp_path)
    assert "[works_at]" in pending.stdout and "Alice  →  Acme" in pending.stdout
    assert f"evidence {data['source_node_id']}: Alice works at Acme" in pending.stdout
    accepted = run_cli(["accept", data["facts"][0]["id"]], tmp_path)
    assert accepted.returncode == 0 and "[works_at]" in accepted.stdout


def test_entities_cli_dated_fact_review_and_invalidation(tmp_path):
    import json
    import shlex
    from graph_engine.brain import Brain

    payload = {
        "entities": [{"name": "Alice", "type": "person"}, {"name": "Acme", "type": "org"}],
        "facts": [{"subject": "Alice", "predicate": "works_at", "object": "Acme",
                   "evidence": "Alice works at Acme", "valid_from": "2000-01-01",
                   "valid_to": "2001-01-01"}],
    }
    env = {"IG_ENTITIES_LLM_CMD": "printf %s " + shlex.quote(json.dumps(payload))}
    args = ["entities", "Alice works at Acme.", "--llm"]
    result = run_cli(args, tmp_path, env)
    assert result.returncode == 0 and "(pending)" in result.stdout
    brain = Brain(tmp_path / "brain", mode="local")
    edge = next(e for e in brain.read_edges() if e.kind == "fact")
    assert edge.id in run_cli(["pending"], tmp_path).stdout
    assert run_cli(["accept", edge.id], tmp_path).returncode == 0
    assert "(accepted)" in run_cli(args, tmp_path, env).stdout
    brain.invalidate_edge(edge.id)
    repeated = run_cli([*args, "--accept-facts"], tmp_path, env)
    assert repeated.returncode == 0 and "(invalidated)" in repeated.stdout
    assert edge.id not in run_cli(["pending"], tmp_path).stdout
    assert len([e for e in brain.read_edges() if e.kind == "fact"]) == 1
