"""CLI for the brain: init, ingest, pending, accept, reject, link, search.

Examples:
  python -m graph_engine init [--remote <brain-repo-url>] [--demo]
  python -m graph_engine ingest "New idea ..." [--source agent/bot] [--allow-dup]
  cat note.md | python -m graph_engine ingest -
  python -m graph_engine pending
  python -m graph_engine accept <edge_id>
  python -m graph_engine reject <edge_id>
  python -m graph_engine accept-pending [--max-intent-per-source 2] [--dry-run] [--json]
  python -m graph_engine recall [--top 10] [--aggregate] [--dry-run] [--json]
  python -m graph_engine link <node_a> <node_b> [--kind same_as]
  python -m graph_engine search "attention" [--json]
  python -m graph_engine gaps [--taxonomy tax.json] [--min 10] [--json]
  python -m graph_engine merge <survivor_id> <deletee_id>   # consolidate a near-dup
  python -m graph_engine near-dup [--lo 0.78] [--hi 0.92]   # report near-duplicate pairs
  python -m graph_engine status [--json]                    # connectivity/hygiene report

Env like the server: IG_BRAIN_PATH, IG_BRAIN_REMOTE, IG_BRAIN_MODE,
IDEAGRAPH_EMBEDDER (st|hash), IDEAGRAPH_EMBEDDER_MODEL.
"""

from __future__ import annotations

import os
import sys

from . import runtime
from .brain_engine import BrainEngine
from .gaps import analyze_coverage, find_gaps, render, load_taxonomy
from .hygiene import near_dup_pairs, connectivity, status_counts, render_near_dup, render_status
from .merge import merge_nodes
from .retrieval import retrieve

# Shared factory (one source of truth for CLI, server and future MCP surface).
make_engine = runtime.make_engine


def _short(text: str, n: int = 70) -> str:
    text = text.replace("\n", " ")
    return text[: n - 1] + "…" if len(text) > n else text


def cmd_observe(engine: BrainEngine, args: list[str]) -> None:
    """Store a raw episodic event (Phase 1: episodic layer)."""
    source = "human"
    observed_at = None
    context = None
    allow_dup = False
    rest: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--source":
            if i + 1 >= len(args):
                print("Usage: ig observe \"text\" --source <source>")
                sys.exit(1)
            source = args[i + 1]
            i += 2
        elif args[i] == "--at":
            if i + 1 >= len(args):
                print("Usage: ig observe \"text\" --at <ISO-8601>")
                sys.exit(1)
            observed_at = args[i + 1]
            i += 2
        elif args[i] == "--context":
            if i + 1 >= len(args):
                print("Usage: ig observe \"text\" --context <context>")
                sys.exit(1)
            context = args[i + 1]
            i += 2
        elif args[i] == "--allow-dup":
            allow_dup = True
            i += 1
        else:
            rest.append(args[i])
            i += 1
    if "-" in rest:
        if len(rest) > 1:
            print("Usage: '-' (stdin) cannot be combined with text arguments.")
            sys.exit(1)
        text = sys.stdin.read()
    else:
        text = " ".join(rest)
    if not text.strip():
        print("Nothing to observe. Usage: ig observe \"text\" | ig observe - < file")
        sys.exit(1)
    node, dup = engine.observe(text, source=source, observed_at=observed_at,
                               context=context, allow_duplicates=allow_dup)
    if dup:
        print(f"Duplicate → merged into {node.id}: {_short(node.text)}")
    else:
        print(f"Episodic {node.id}: {_short(node.text)}")
        if observed_at:
            print(f"  observed_at: {observed_at}")
        if context:
            print(f"  context: {context}")


def cmd_extract(engine: BrainEngine, args: list[str]) -> None:
    """Extract a semantic fact from an episodic node (Phase 1)."""
    if not args:
        print("Usage: ig extract <episodic_node_id> [\"semantic text\"]")
        sys.exit(1)
    node_id = args[0]
    text = " ".join(args[1:]) if len(args) > 1 else None
    try:
        node = engine.extract(node_id, text=text)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"Semantic {node.id}: {_short(node.text)}")
    print(f"  extracted from episodic {node_id}")


def cmd_timeline(engine: BrainEngine, args: list[str]) -> None:
    """Query episodic nodes by time range (Phase 1: temporal reasoning)."""
    since = None
    until = None
    limit = 50
    i = 0
    while i < len(args):
        if args[i] == "--since":
            if i + 1 >= len(args):
                print("Usage: ig timeline --since <ISO-8601>")
                sys.exit(1)
            since = args[i + 1]
            i += 2
        elif args[i] == "--until":
            if i + 1 >= len(args):
                print("Usage: ig timeline --until <ISO-8601>")
                sys.exit(1)
            until = args[i + 1]
            i += 2
        elif args[i] == "--limit":
            if i + 1 >= len(args):
                print("Usage: ig timeline --limit <n>")
                sys.exit(1)
            limit = int(args[i + 1])
            i += 2
        else:
            i += 1
    nodes = engine.timeline(since=since, until=until, limit=limit)
    if not nodes:
        print("No episodic nodes found.")
        return
    print(f"Timeline ({len(nodes)} episodic nodes):")
    for n in nodes:
        ts = n.observed_at or n.created
        ctx = f" [{n.context}]" if n.context else ""
        print(f"  {ts}  {n.id[:8]}  {_short(n.text, 60)}{ctx}")


def cmd_valid_at(engine: BrainEngine, args: list[str]) -> None:
    """Show the graph as it was at a point in time (Phase 2: temporal reasoning)."""
    if not args:
        print("Usage: ig valid-at <ISO-8601>")
        sys.exit(1)
    timestamp = args[0]
    try:
        result = engine.valid_at(timestamp)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    nodes = result["nodes"]
    edges = result["edges"]
    print(f"Graph at {timestamp}: {len(nodes)} nodes, {len(edges)} edges")
    for n in nodes[:20]:
        print(f"  {n.id[:8]}  [{n.ntype}]  {_short(n.text, 60)}")
    if len(nodes) > 20:
        print(f"  … and {len(nodes) - 20} more nodes")
    for e in edges[:20]:
        print(f"  {e.source[:8]} --[{e.kind}]--> {e.target[:8]}  (from {e.valid_from})")
    if len(edges) > 20:
        print(f"  … and {len(edges) - 20} more edges")


def cmd_history(engine: BrainEngine, args: list[str]) -> None:
    """Show how a node's edges evolved over time (Phase 2: temporal reasoning)."""
    if not args:
        print("Usage: ig history <node_id>")
        sys.exit(1)
    node_id = args[0]
    events = engine.history(node_id)
    if not events:
        print(f"No edge history for node {node_id}.")
        return
    print(f"History of node {node_id} ({len(events)} events):")
    for ev in events:
        other = ev.get("other_node", "?")
        origin = f" [{ev['origin']}]" if ev.get("origin") else ""
        rejected = " (rejected)" if ev.get("rejected") else ""
        print(f"  {ev['timestamp']}  {ev['event']:12s}  --[{ev['kind']}]-->  {other[:8]}{origin}{rejected}")


def cmd_when(engine: BrainEngine, args: list[str]) -> None:
    """Retrieval restricted to what was known at a point in time (Phase 2)."""
    if len(args) < 2:
        print("Usage: ig when <ISO-8601> <query>")
        sys.exit(1)
    timestamp = args[0]
    query = " ".join(args[1:])
    try:
        results = engine.when(query, timestamp)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    if not results:
        print(f"No results for {query!r} at {timestamp}.")
        return
    print(f"Results for {query!r} at {timestamp}:")
    for node_id, score in results:
        node = engine.brain.read_node(node_id)
        text = _short(node.text, 60) if node else "?"
        print(f"  {score:.4f}  {node_id[:8]}  {text}")


def cmd_context(engine: BrainEngine, args: list[str]) -> None:
    """Build a context window for a query (Phase 3: context management)."""
    budget = 4000
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    i = 0
    while i < len(args):
        if args[i] == "--budget" and i + 1 < len(args):
            budget = int(args[i + 1])
            i += 2
        else:
            i += 1
    if not args:
        print("Usage: ig context <query> [--budget <tokens>] [--json]")
        sys.exit(1)
    query = " ".join(args)
    result = engine.build_context(query, budget=budget)
    if as_json:
        import json as _json
        print(_json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["context"])
        print(f"\n--- {result['tokens']} tokens (budget {result['budget']})"
              f"{', truncated' if result['truncated'] else ''} ---")


def cmd_ingest(engine: BrainEngine, args: list[str]) -> None:
    source = "human"
    allow_dup = False
    rest: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--source":
            # Audit #26: fehlender Wert nach --source ist ein Usage-Fehler,
            # kein IndexError-Traceback.
            if i + 1 >= len(args):
                print("Usage: ig ingest \"text\" --source <source>")
                sys.exit(1)
            source = args[i + 1]
            i += 2
        elif args[i] == "--allow-dup":
            allow_dup = True
            i += 1
        else:
            rest.append(args[i])
            i += 1
    # Audit #32: '-' is the stdin marker, also in mixed args. Before,
    # 'ig ingest - extra' used to ingest the literal text "- extra"
    # (exit 0, node created). A '-' token means stdin; extra text
    # next to it is an error.
    if "-" in rest:
        if len(rest) > 1:
            print("Usage: '-' (stdin) cannot be combined with text arguments.")
            sys.exit(1)
        text = sys.stdin.read()
    else:
        text = " ".join(rest)
    if not text.strip():
        print("Nothing to ingest. Usage: ig ingest \"text\" | ig ingest - < file")
        sys.exit(1)
    node, edges, dup = engine.ingest(text, source=source, allow_duplicates=allow_dup)
    if dup:
        print(f"Duplicate → merged into {node.id}: {_short(node.text)}")
    else:
        print(f"Node {node.id}: {_short(node.text)}")
        for e in edges:
            print(f"  Suggestion: --[{e.kind}]--> {e.target} ({e.id})")


def cmd_pending(engine: BrainEngine, args: list[str]) -> None:
    edges = [e for e in engine.brain.read_edges() if e.pending]
    texts = {n.id: n.text for n in engine.brain.read_nodes()}
    if not edges:
        print("No pending suggestions.")
        return
    for e in edges:
        print(f"{e.id}  [{e.kind}]  {_short(texts.get(e.source, e.source), 40)}"
              f"  ↔  {_short(texts.get(e.target, e.target), 40)}")
    print(f"\n{len(edges)} pending · akzeptieren: ig accept {edges[0].id}")


def _first_or_usage(args: list[str], cmd: str) -> str:
    """Audit #26: a missing positional argument prints the usage line
    instead of raising IndexError."""
    if not args:
        print(f"Usage: ig {cmd} <edge_id>")
        sys.exit(1)
    return args[0]


def _resolve_cmd(engine: BrainEngine, edge_id: str, accept: bool) -> None:
    edge = engine.resolve(edge_id, accept)
    if edge is None:
        print(f"Edge {edge_id} not found or not pending.")
        sys.exit(1)
    print(f"{'accepted' if accept else 'rejected'}: {edge_id} [{edge.kind}]")


def cmd_link(engine: BrainEngine, args: list[str]) -> None:
    kind = "same_as"
    if "--kind" in args:
        i = args.index("--kind")
        # Audit #26: a missing value after --kind is a usage error, not an IndexError.
        if i + 1 >= len(args):
            print("Usage: ig link <node_a> <node_b> [--kind same_as]")
            sys.exit(1)
        kind = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) != 2:
        print("Usage: ig link <node_a> <node_b> [--kind same_as]")
        sys.exit(1)
    try:
        edge = engine.link(args[0], args[1], kind)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    print(f"verlinkt: {edge.source} --[{edge.kind}]--> {edge.target}")


def cmd_init(engine: BrainEngine, args: list[str]) -> None:
    remote = None
    demo = "--demo" in args
    if "--remote" in args:
        i = args.index("--remote")
        remote = args[i + 1] if i + 1 < len(args) else None
    brain = engine.brain
    if demo:
        from .demo import build_demo_brain
        try:
            stats = build_demo_brain(str(brain.path))
        except FileExistsError:
            # Audit #58: friendly message instead of a raw traceback — a
            # non-empty directory is never overwritten.
            print(f"Error: {brain.path} already exists and is not empty.")
            print("The demo brain is never written into an existing directory.")
            print("Choose a different path: IG_BRAIN_PATH=<path> ig init --demo")
            sys.exit(1)
        print(f"✓ Demo brain initialized: {brain.path}")
        print(f"  {stats['nodes']} nodes · {stats['edges']} edges "
              f"({stats['pending']} pending for HITL review)")
        print("  Includes: all edge types, 1 orphan island (demos `ig status`),")
        print("  1 near-dup pair (demos `ig near-dup` + `ig merge`), 1 same_as pair.")
        print("Try it out:")
        print("  ig status                     # island + hygiene report")
        print("  ig near-dup                   # find the demo near-dup pair")
        print("  ig pending                    # review the 2 pending suggestions")
        print("  ig search \"RAG\"               # hybrid search (works instantly)")
        print("  uvicorn graph_engine.server:app --port 8000   # → http://localhost:8000")
        return
    if (brain.path / "INDEX.md").exists() or (brain.path / "nodes").exists():
        # same #58 principle for plain init: never clobber an existing brain
        print(f"Error: {brain.path} already contains a brain.")
        print("Choose a different path: IG_BRAIN_PATH=<path> ig init")
        sys.exit(1)
    brain.init(remote=remote, commit=True)
    print(f"✓ Brain repo initialized: {brain.path}")
    mode_line = f"  Mode: {brain.mode}"
    mode_line += (f" · Remote: {remote}" if remote else " (local, no remote)")
    print(mode_line)
    print("  Structure: nodes/ · edges.jsonl · vectors.jsonl · INDEX.md")
    print("Get started:")
    print('  ig ingest "First idea ..."            # CLI ingest')
    print("  uvicorn graph_engine.server:app --port 8000   # → http://localhost:8000")


def cmd_gaps(engine: BrainEngine, args: list[str]) -> None:
    taxonomy = None
    threshold = 10
    as_json = False
    i = 0
    while i < len(args):
        if args[i] == "--taxonomy" and i + 1 < len(args):
            taxonomy = load_taxonomy(args[i + 1])
            i += 2
        elif args[i] == "--min" and i + 1 < len(args):
            # Audit #26: non-numeric --min values are a usage error, not a ValueError traceback.
            try:
                threshold = int(args[i + 1])
            except ValueError:
                print(f"Usage: --min expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--json":
            as_json = True
            i += 1
        else:
            i += 1
    cov = analyze_coverage(engine.brain, taxonomy)
    if as_json:
        import json as _json
        print(_json.dumps({
            "total": cov.total,
            "areas": [{"name": a.name, "count": a.count} for a in cov.areas],
            "gaps": [a.name for a in find_gaps(cov, threshold)],
            "unclassified": cov.unclassified,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(cov, threshold))


def cmd_communities(engine: BrainEngine, args: list[str]) -> None:
    """Read-only topology report: communities, god nodes, structural gaps."""
    from .communities import analyze_communities, render_communities

    min_size = 15
    top = 10
    betweenness_sample: int | None = None
    include_pending = True
    with_members = False
    as_json = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--min-size" and i + 1 < len(args):
            try:
                min_size = int(args[i + 1])
            except ValueError:
                print(f"Usage: --min-size expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif arg == "--top" and i + 1 < len(args):
            try:
                top = int(args[i + 1])
            except ValueError:
                print(f"Usage: --top expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif arg == "--betweenness-sample" and i + 1 < len(args):
            try:
                betweenness_sample = int(args[i + 1])
            except ValueError:
                print(f"Usage: --betweenness-sample expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif arg == "--no-pending":
            include_pending = False
            i += 1
        elif arg == "--members":
            with_members = True
            i += 1
        elif arg == "--json":
            as_json = True
            i += 1
        else:
            i += 1
    rep = analyze_communities(engine.brain, min_size=min_size, top=top,
                              betweenness_sample=betweenness_sample,
                              include_pending=include_pending,
                              with_members=with_members)
    if as_json:
        import json as _json
        payload = {
            "nodes": rep.nodes,
            "edges": rep.edges,
            "modularity": round(rep.modularity, 4),
            "betweenness_sample": rep.betweenness_sample,
            "communities": [{
                "id": c.id,
                "size": c.size,
                "degree_sum": c.degree_sum,
                "internal_edges": c.internal_edges,
                "label": c.label,
                "sample": c.sample,
                **({"members": c.members} if with_members else {}),
            } for c in rep.communities],
            "god_nodes": [{
                "id": g.id, "degree": g.degree,
                "betweenness": g.betweenness, "text": g.text,
            } for g in rep.god_nodes],
            "gaps": [{
                "a": g.a, "b": g.b,
                "a_label": g.a_label, "b_label": g.b_label,
                "a_size": g.a_size, "b_size": g.b_size,
                "observed_edges": g.observed_edges,
                "expected_edges": g.expected_edges,
                "deficit": g.deficit,
                "bridge_nodes": g.bridge_nodes,
                "a_samples": g.a_samples, "b_samples": g.b_samples,
            } for g in rep.gaps],
            "isolated": rep.isolated,
            "unclassified": rep.unclassified,
        }
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_communities(rep))


def cmd_report(engine: BrainEngine, args: list[str]) -> None:
    """One-page state-of-the-brain digest (read-only)."""
    from .report import render_report, report_data
    import json as _json

    since = None
    top = None
    as_json = False
    write = False
    coverage = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--since" and i + 1 < len(args):
            since = args[i + 1]
            i += 2
        elif arg == "--top" and i + 1 < len(args):
            try:
                top = int(args[i + 1])
            except ValueError:
                print(f"Usage: --top expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif arg == "--json":
            as_json = True
            i += 1
        elif arg == "--write":
            write = True
            i += 1
        elif arg == "--coverage":
            coverage = True
            i += 1
        else:
            i += 1
    opts: dict = {}
    if since is not None:
        # Accept hours (int/float) or ISO — reject anything else BEFORE doing
        # any work (usage error, not a traceback mid-render).
        from .report import _parse_since
        try:
            _parse_since({"since": since})
        except (ValueError, TypeError):
            print(f"Usage: --since expects hours (e.g. 24) or ISO datetime, "
                  f"got: {since!r}")
            sys.exit(1)
        opts["since"] = since
    if top is not None:
        opts["top"] = top
    if coverage:
        opts["coverage"] = True
    if as_json:
        print(_json.dumps(report_data(engine.brain, **opts),
                          ensure_ascii=False, indent=2))
    else:
        out = render_report(engine.brain, **opts)
        # A blank generated artifact destroys the workflow value (Graphify
        # GRAPH_REPORT.md lesson): guard the body at runtime.
        if len(out.strip()) < 50:
            print("Error: report body is empty — the brain may be unreadable")
            sys.exit(1)
        print(out)
    if write:
        from .report import write_report
        try:
            write_report(engine.brain, **opts)
        except RuntimeError as exc:
            print(f"Error: {exc}")
            sys.exit(1)
        if engine.brain.mode == "git":
            engine.brain.commit_and_push("report: regenerate BRAIN_REPORT.md")
            print("written: BRAIN_REPORT.md (committed)")
        else:
            print("written: BRAIN_REPORT.md (local mode, no commit)")


def cmd_merge(engine: BrainEngine, args: list[str]) -> None:
    if len(args) != 2:
        print("Usage: ig merge <survivor_id> <deletee_id>  (consolidates deletee into survivor)")
        sys.exit(1)
    survivor, deletee = args[0], args[1]
    try:
        r = merge_nodes(engine.brain, survivor, deletee, embedder=engine.embedder)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    print(f"merge: {r.deletee} consolidated into {r.survivor}")
    print(f"  edges redirected: {r.edges_redirected} · removed: {r.edges_removed}")


def cmd_near_dup(engine: BrainEngine, args: list[str]) -> None:
    lo, hi, max_pairs, as_json = 0.78, 0.92, None, False
    i = 0
    while i < len(args):
        if args[i] == "--lo" and i + 1 < len(args):
            try:
                lo = float(args[i + 1])
            except ValueError:
                print(f"Usage: --lo expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--hi" and i + 1 < len(args):
            try:
                hi = float(args[i + 1])
            except ValueError:
                print(f"Usage: --hi expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--max" and i + 1 < len(args):
            try:
                max_pairs = int(args[i + 1])
            except ValueError:
                print(f"Usage: --max expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--json":
            as_json = True; i += 1
        else:
            i += 1
    # Audit #26 (Semantik): --lo >= --hi ist eine leere/invalide Band-Angabe;
    # --max 0 means "0 pairs" (a limit), not "unlimited".
    if lo >= hi:
        print(f"Usage: --lo ({lo}) must be smaller than --hi ({hi}).")
        sys.exit(1)
    if max_pairs is not None and max_pairs < 0:
        print("Usage: --max expects a non-negative number.")
        sys.exit(1)
    pairs = near_dup_pairs(engine.brain, lo=lo, hi=hi, max_pairs=max_pairs)
    if as_json:
        import json as _json
        print(_json.dumps(
            [{"score": p.score, "a": p.a, "b": p.b, "a_text": p.a_text, "b_text": p.b_text}
             for p in pairs], ensure_ascii=False, indent=2))
    else:
        print(render_near_dup(pairs))


def cmd_status(engine: BrainEngine, args: list[str]) -> None:
    as_json = "--json" in args
    if as_json:
        import json as _json
        c = connectivity(engine.brain)
        print(_json.dumps({
            "total": c.total, "edges": c.edges, "max_degree": c.max_degree,
            "mean_degree": round(c.mean_degree, 2),
            "orphans": len(c.orphans), "islands": len(c.islands), "weak": len(c.weak),
            "status": dict(status_counts(engine.brain)),
        }, ensure_ascii=False, indent=2))
    else:
        print(render_status(engine.brain))


def cmd_search(engine: BrainEngine, args: list[str]) -> None:
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if not args:
        print("Usage: ig search <term> [--json]")
        sys.exit(1)
    q = " ".join(args)
    id2node = {n.id: n for n in engine.brain.read_nodes()}
    # track=True: the CLI is the human/agent search surface, so its queries feed
    # the recall ledger (gitignored append, aggregated by `ig recall
    # --aggregate`). The MCP surface stays untracked (strictly read-only).
    hits = retrieve(engine, q, k=5, track=True)
    if as_json:
        import json as _json
        results = []
        for nid, score in hits:
            n = id2node.get(nid)
            if n is None:
                continue
            results.append({
                "id": nid,
                # RRF rank-fusion score, NOT a similarity — do not compare
                # it across queries or read it as a confidence.
                "score": round(score, 4),
                "snippet": _short(n.text, 200),
                "status": n.status,
                "type": n.ntype,
                "tags": list(n.tags or []),
                "created": n.created,
            })
        print(_json.dumps({"query": q, "count": len(results), "results": results},
                          ensure_ascii=False, indent=2))
        return
    for nid, score in hits:
        n = id2node.get(nid)
        if n is not None:
            print(f"{nid}  {score:.3f}  {_short(n.text)}")
    print(f"\n{len(hits)} hits (hybrid dense+BM25)")


def cmd_mcp(engine: BrainEngine, args: list[str]) -> None:
    """MCP server over stdio. Read-only by default; `--write` adds the agent
    memory tools (remember / recall / forget) — an opt-in, because a
    model-initiated write commits AND pushes to a private repo."""
    write = "--write" in args
    unknown = [a for a in args if a != "--write"]
    if unknown:
        print(f"Unknown option for mcp: {unknown[0]!r} (only --write is supported)")
        sys.exit(1)
    if write:
        # Set BEFORE importing the module: tool registration and the server
        # instructions are decided at import time.
        os.environ["IG_MCP_WRITE"] = "1"
    try:
        from .mcp.server import main as mcp_main
    except ImportError:
        print("MCP support is not installed — pip install 'graph-engine[mcp]'")
        sys.exit(1)
    if write:
        from .mcp.server import register_write_tools
        register_write_tools()
    mcp_main()


def cmd_accept_pending(engine: BrainEngine, args: list[str]) -> None:
    """Review policy: accept pending suggestions, cap intent fan-out per source.

    Non-intent pending edges are accepted; intent edges beyond
    `--max-intent-per-source` (default 2, env IG_INTENT_AUTO_ACCEPT_MAX) stay
    pending for `ig pending`. One commit for the whole batch.
    """
    max_intent, dry_run, as_json = None, False, False
    i = 0
    while i < len(args):
        if args[i] == "--max-intent-per-source" and i + 1 < len(args):
            try:
                max_intent = int(args[i + 1])
            except ValueError:
                print(f"Usage: --max-intent-per-source expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            if max_intent < 0:
                print("Usage: --max-intent-per-source must be >= 0")
                sys.exit(1)
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        elif args[i] == "--json":
            as_json = True
            i += 1
        else:
            print(f"Unknown option for accept-pending: {args[i]!r}")
            sys.exit(1)
    from .review import accept_pending
    res = accept_pending(engine.brain, max_intent_per_source=max_intent,
                         dry_run=dry_run)
    if as_json:
        import json as _json
        print(_json.dumps(res, ensure_ascii=False, indent=2))
        return
    verb = "would accept" if dry_run else "accepted"
    print(f"{verb} {len(res['accepted'])} pending edge(s); "
          f"held {len(res['held'])} intent edge(s) for review "
          f"(cap {res['cap']} per source)")
    if res["held"]:
        print("Review them with: ig pending")


def cmd_recall(engine: BrainEngine, args: list[str]) -> None:
    """Recall statistics: what the memory is actually asked for.

    Without flags: the most-recalled nodes (derived counters) + ledger size.
    `--aggregate` folds the ledger into the node counters in one commit
    (`--dry-run` to preview, `--json` for machines).
    """
    top_n, aggregate, dry_run, as_json = 10, False, False, False
    i = 0
    while i < len(args):
        if args[i] == "--top" and i + 1 < len(args):
            try:
                top_n = int(args[i + 1])
            except ValueError:
                print(f"Usage: --top expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--aggregate":
            aggregate = True
            i += 1
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        elif args[i] == "--json":
            as_json = True
            i += 1
        else:
            print(f"Unknown option for recall: {args[i]!r}")
            sys.exit(1)

    from .recall import aggregate as aggregate_recalls, ledger_path, read_ledger, top
    if aggregate:
        res = aggregate_recalls(engine.brain, dry_run=dry_run)
        if as_json:
            import json as _json
            print(_json.dumps(res, ensure_ascii=False, indent=2))
            return
        verb = "would fold" if dry_run else "folded"
        print(f"{verb} {res['ledger_entries']} ledger entries into {res['nodes']} node(s) "
              f"({res['recalls']} recalls)")
        if dry_run:
            print("Dry run — nothing written.")
        return

    rows = top(engine.brain, top_n)
    ledger = read_ledger(engine.brain)
    id2node = {n.id: n for n in engine.brain.read_nodes()}
    if as_json:
        import json as _json
        print(_json.dumps({
            "ledger_entries": len(ledger),
            "ledger_path": str(ledger_path(engine.brain)),
            "top": [{"id": nid, "recall_count": c,
                     "snippet": _short(id2node[nid].text, 120)}
                    for nid, c in rows if nid in id2node],
        }, ensure_ascii=False, indent=2))
        return
    print(f"recall ledger: {len(ledger)} unaggregated entr"
          f"{'y' if len(ledger) == 1 else 'ies'}")
    if not rows:
        print("no node has been recalled yet — run `ig recall --aggregate` "
              "after some searches")
        return
    print("most-recalled nodes:")
    for nid, count in rows:
        node = id2node.get(nid)
        if node is None:
            continue
        print(f"  {count:4}x  {nid}  {_short(node.text, 90)}")


def cmd_dream(engine: BrainEngine, args: list[str]) -> None:
    """The dream pass: plan (default, read-only), refresh, distill.

    No flags = the eligibility report (nothing written). `--refresh` runs the
    deterministic maintenance, `--distill` writes one abstraction node per
    community (extractive by default; `--llm` needs IG_DREAM_LLM_CMD, a shell
    command that reads the digest on stdin and prints the summary).
    """
    from .dream import (DECAY_DAYS, DECAY_MAX_DEGREE, DREAM_MAX_DISTILL,
                        DREAM_MIN_COMMUNITY, PROMOTE_MIN_DEGREE,
                        PROMOTE_MIN_RECALL, distill, lifecycle, plan, refresh)
    do_refresh, do_distill, dry_run, as_json = False, False, False, False
    do_life, use_llm = False, False
    min_size, limit = DREAM_MIN_COMMUNITY, DREAM_MAX_DISTILL
    min_recall, min_degree = PROMOTE_MIN_RECALL, PROMOTE_MIN_DEGREE
    stale_days, max_degree = DECAY_DAYS, DECAY_MAX_DEGREE
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--refresh":
            do_refresh, i = True, i + 1
        elif a == "--distill":
            do_distill, i = True, i + 1
        elif a == "--lifecycle":
            do_life, i = True, i + 1
        elif a == "--dry-run":
            dry_run, i = True, i + 1
        elif a == "--json":
            as_json, i = True, i + 1
        elif a == "--llm":
            use_llm, i = True, i + 1
        elif a in ("--min-size", "--limit", "--min-recall", "--min-degree",
                   "--stale-days", "--max-degree") and i + 1 < len(args):
            try:
                value = int(args[i + 1])
            except ValueError:
                print(f"Usage: {a} expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            if a == "--min-size":
                min_size = value
            elif a == "--limit":
                limit = value
            elif a == "--min-recall":
                min_recall = value
            elif a == "--min-degree":
                min_degree = value
            elif a == "--stale-days":
                stale_days = value
            else:
                max_degree = value
            i += 2
        else:
            print(f"Unknown option for dream: {a!r}")
            sys.exit(1)

    summarizer = _dream_summarizer() if use_llm else None

    if not do_refresh and not do_distill and not do_life:
        result = plan(engine.brain, min_recall=min_recall, min_degree=min_degree,
                      stale_days=stale_days, min_community=min_size)
        if as_json:
            import json as _json
            print(_json.dumps({
                "nodes": result.nodes, "edges": result.edges,
                "promotion_candidates": len(result.promotion_candidates),
                "decay_candidates": len(result.decay_candidates),
                "merge_candidates": len(result.merge_candidates),
                "distill_candidates": result.distill_candidates,
                "refresh": result.refresh,
            }, ensure_ascii=False, indent=2))
            return
        print(result.render())
        print("\nNothing written. Use --refresh / --distill / --lifecycle to run a pass.")
        return

    out = {}
    if do_refresh:
        out["refresh"] = refresh(engine.brain, dry_run=dry_run)
    if do_distill:
        out["distill"] = distill(engine.brain, min_size=min_size, limit=limit,
                                 summarizer=summarizer, dry_run=dry_run)
    if do_life:
        out["lifecycle"] = lifecycle(engine.brain, min_recall=min_recall,
                                     min_degree=min_degree, stale_days=stale_days,
                                     max_degree=max_degree, dry_run=dry_run)
    if as_json:
        import json as _json
        print(_json.dumps(out, ensure_ascii=False, indent=2))
        return
    if "refresh" in out:
        r = out["refresh"]
        print(f"refresh: {r['kind_changes']} kind(s) re-derived, "
              f"{r['recalls']} recall(s) folded into {r['recall_nodes']} node(s)"
              + (" (dry run)" if r["dry_run"] else ""))
    if "distill" in out:
        d = out["distill"]
        print(f"distill: {d['summaries']} summar{'y' if d['summaries'] == 1 else 'ies'} "
              f"from {d['communities']} communit{'y' if d['communities'] == 1 else 'ies'}, "
              f"{d['edges']} consolidator edge(s)"
              + (" (extractive)" if not d["used_llm"] else " (llm)")
              + (" (dry run)" if d["dry_run"] else ""))
    if "lifecycle" in out:
        life = out["lifecycle"]
        c = life["candidates"]
        print(f"lifecycle: {life['promoted']} promoted, {life['revived']} revived, "
              f"{life['staled']} staled (candidates: {c['promote']} to promote, "
              f"{c['revive']} to revive, {c['decay']} to decay)"
              + (" (dry run)" if life["dry_run"] else ""))


def _dream_summarizer():
    """`--llm`: a shell command that turns the extractive digest into prose.

    No provider coupling in the engine (the repo has no LLM dependency): the
    command is configured as IG_DREAM_LLM_CMD, receives the digest on stdin and
    must print the summary on stdout.
    """
    import os
    import subprocess
    cmd = os.environ.get("IG_DREAM_LLM_CMD", "").strip()
    if not cmd:
        print("--llm needs IG_DREAM_LLM_CMD (a shell command reading the digest on "
              "stdin and printing the summary on stdout).")
        sys.exit(1)

    def summarizer(digest: str) -> str:
        proc = subprocess.run(cmd, shell=True, input=digest, capture_output=True,
                              text=True, timeout=300)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise RuntimeError(f"IG_DREAM_LLM_CMD failed ({proc.returncode}): "
                               f"{proc.stderr.strip()[:200]}")
        return proc.stdout.strip()

    return summarizer


COMMANDS = {
    "init": cmd_init,
    "ingest": cmd_ingest,
    "observe": cmd_observe,
    "extract": cmd_extract,
    "timeline": cmd_timeline,
    "valid-at": cmd_valid_at,
    "history": cmd_history,
    "when": cmd_when,
    "context": cmd_context,
    "pending": lambda e, a: cmd_pending(e, a),
    "accept": lambda e, a: _resolve_cmd(e, _first_or_usage(a, "accept"), True),
    "reject": lambda e, a: _resolve_cmd(e, _first_or_usage(a, "reject"), False),
    "link": cmd_link,
    "search": cmd_search,
    "gaps": cmd_gaps,
    "merge": cmd_merge,
    "near-dup": cmd_near_dup,
    "status": cmd_status,
    "communities": cmd_communities,
    "report": cmd_report,
    "mcp": cmd_mcp,
    "accept-pending": cmd_accept_pending,
    "dream": cmd_dream,
    "recall": cmd_recall,
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    cmd, rest = args[0], args[1:]
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(f"Unknown command: {cmd}. Available: {', '.join(COMMANDS)}")
        sys.exit(1)
    fn(make_engine(), rest)


if __name__ == "__main__":
    main()
