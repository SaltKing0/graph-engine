"""Brain layer: the private git repo as memory.

Structure inside the brain repo:
  nodes/<id>.md     — one idea per file (YAML frontmatter + text)
  edges.jsonl       — one edge per line (machine-written, pending flag)
  INDEX.md          — generated table of contents (humans + GitHub search)

Sync model: pull before every write, commit+push after.
For tests: mode="local" works without git in a temp dir.

Crash safety (Audit #2): all whole-file writes go through
_atomic_write() — first to a temp file in the same directory, then
os.replace(). A crash mid-write leaves either the old or the new
file, never a half-written one.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


VALID_STATUS = ("probation", "active", "stale", "tombstone")


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically: temp file in the same directory + os.replace()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:8])
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class Node:
    def __init__(self, text: str, id: str | None = None, created: str | None = None,
                 source: str = "human", tags: list[str] | None = None,
                 sources: list[str] | None = None, ntype: str = "semantic",
                 status: str = "probation",
                 recall_count: int = 0, recall_queries: list[str] | None = None,
                 last_recalled: str | None = None,
                 observed_at: str | None = None, context: str | None = None):
        self.text = text
        self.id = id or uuid.uuid4().hex[:12]
        self.created = created or _now_iso()
        self.source = source
        self.tags = tags or []
        # Audit #54 (churn fix): new nodes record their source IMMEDIATELY in
        # `sources` (and to_markdown always writes the list) — otherwise the
        # file gains a purely cosmetic sources: line on the first dup ingest.
        # from_markdown passes [] explicitly → old files without the line
        # stay unchanged until they really mutate.
        self.sources = sources if sources is not None else [source]
        # Taxonomy (LangGraph/survey lesson): semantic | episodic | procedural
        self.ntype = ntype if ntype in ("semantic", "episodic", "procedural") else "semantic"
        # V2#2 memory hygiene: dual buffer — new nodes start in probation,
        # get promoted after dedup/verification, or end up as tombstones.
        self.status = status if status in VALID_STATUS else "probation"
        # Recall tracking (the signal a memory system needs and this one never
        # had): how often a node was actually retrieved, over how many DISTINCT
        # queries, and when last. OpenClaw's dreaming promotion gates are built
        # on exactly these three numbers; without them "promote what is used"
        # cannot be decided. Derived data: written by `recall.aggregate()` from
        # the local ledger, never on the read path itself.
        self.recall_count = int(recall_count or 0)
        self.recall_queries = list(recall_queries or [])
        self.last_recalled = last_recalled
        # Episodic layer (Phase 1): when/where this observation was made.
        # Only meaningful for ntype="episodic"; None for semantic/procedural.
        self.observed_at = observed_at
        self.context = context

    def to_markdown(self) -> str:
        tags = "[" + ", ".join(self.tags) + "]" if self.tags else "[]"
        lines = [f"id: {self.id}", f"created: {self.created}",
                 f"source: {self.source}", f"type: {self.ntype}",
                 f"status: {self.status}"]
        # always write sources (even empty) — otherwise the file gains a
        # purely cosmetic sources: line on the first dup ingest (history churn,
        # Audit #54): from_markdown returns [], merge_node inserts node.source,
        # the rewrite "changes" the file without any content gain.
        lines.append("sources: [" + ", ".join(self.sources) + "]")
        lines.append(f"tags: {tags}")
        # Episodic metadata only when present — semantic/procedural nodes
        # stay unchanged (no frontmatter churn).
        if self.ntype == "episodic":
            if self.observed_at:
                lines.append(f"observed_at: {self.observed_at}")
            if self.context:
                lines.append(f"context: {self.context}")
        # Recall stats only when they exist — writing them unconditionally
        # would rewrite all ~2k node files for zero information.
        if self.recall_count:
            lines.append(f"recalls: {self.recall_count}")
            lines.append("recall_queries: [" + ", ".join(self.recall_queries) + "]")
            if self.last_recalled:
                lines.append(f"last_recalled: {self.last_recalled}")
        return "---\n" + "\n".join(lines) + "\n---\n\n" + f"{self.text}\n"

    @classmethod
    def from_markdown(cls, raw: str) -> "Node":
        m = re.match(r"^---\n(.*?)\n---\n\n?(.*)$", raw, re.DOTALL)
        if not m:
            raise ValueError("No frontmatter found")
        meta_raw, text = m.group(1), m.group(2)
        meta: dict = {}
        for line in meta_raw.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip()
        # Audit #56: a hand-edited file without id: should raise an
        # understandable error (with path context so the caller can skip it),
        # not a bare KeyError.
        if "id" not in meta:
            raise ValueError("Frontmatter without 'id:' — skipping file")
        tags = [t.strip() for t in meta.get("tags", "[]").strip("[]").split(",") if t.strip()]
        sources = [s.strip() for s in meta.get("sources", "").strip("[]").split(",") if s.strip()]
        try:
            recall_count = int(meta.get("recalls", "0") or 0)
        except ValueError:
            recall_count = 0
        recall_queries = [q.strip() for q in
                          meta.get("recall_queries", "").strip("[]").split(",") if q.strip()]
        return cls(text=text.strip(), id=meta["id"], created=meta.get("created"),
                   source=meta.get("source", "human"), tags=tags, sources=sources,
                   ntype=meta.get("type", "semantic"), status=meta.get("status", "probation"),
                   recall_count=recall_count, recall_queries=recall_queries,
                   last_recalled=meta.get("last_recalled"),
                   observed_at=meta.get("observed_at"),
                   context=meta.get("context"))

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "created": self.created,
                "source": self.source, "tags": self.tags, "sources": self.sources,
                "type": self.ntype, "status": self.status,
                "recall_count": self.recall_count,
                "recall_queries": self.recall_queries,
                "last_recalled": self.last_recalled,
                "observed_at": self.observed_at, "context": self.context}


class Edge:
    def __init__(self, source: str, target: str, kind: str,
                 pending: bool = True, id: str | None = None,
                 valid_from: str | None = None, valid_to: str | None = None,
                 confidence: float | None = None,
                 invalidated_by: str | None = None, rejected: bool = False,
                 origin: str | None = None):
        self.source = source
        self.target = target
        self.kind = kind
        self.pending = pending
        self.id = id or uuid.uuid4().hex[:12]
        # Provenance of the EDGE ITSELF (who created it): "suggester" (cosine
        # kNN), "intent" (marker heuristic), "manual" (ig link / declared
        # relations / demo seed), "consolidator" (a dream pass). None = legacy
        # edge written before the field existed. Reports and maintenance passes
        # must treat heuristic edges as rewritable and manual ones as
        # user-authored — without this, "which edges are machine guesses?" can
        # only be reconstructed from the text (done by hand once, 2026-09-18).
        self.origin = origin
        # Bi-temporality (Zep/Graphiti lesson): fact validity kept separate
        # from commit time (which the git history provides for free).
        self.valid_from = valid_from or _now_iso()
        self.valid_to = valid_to  # None = currently valid; set = invalidated
        # V2#3: confidence (cosine) of auto suggestions; None for manual links.
        self.confidence = confidence
        # V1#1: provenance — which edge/event invalidated this edge.
        self.invalidated_by = invalidated_by
        self.rejected = rejected

    def to_dict(self) -> dict:
        result = {"id": self.id, "source": self.source, "target": self.target,
                "kind": self.kind, "pending": self.pending,
                "valid_from": self.valid_from, "valid_to": self.valid_to,
                "confidence": self.confidence,
                "invalidated_by": self.invalidated_by}
        if self.origin is not None:
            result["origin"] = self.origin
        if self.rejected:
            result["rejected"] = True
        return result


def _jsonl_dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


class Brain:
    """The private repo as storage. mode="git" syncs, mode="local" is FS-only."""

    def __init__(self, path: str, remote: str | None = None, mode: str = "local"):
        self.path = Path(path)
        self.remote = remote
        self.mode = mode
        # Instance lock: serializes RMW mutations even when MULTIPLE
        # BrainEngine instances share the same brain (the server builds a new
        # engine per request). Multi-step chains (ingest) must stay consistent
        # across several calls — the engine-wide BRAIN_LOCK and this instance
        # lock combine cleanly for that (RLock).
        self._lock = threading.RLock()

    # ---------- Git sync ----------

    @staticmethod
    def _remote_has_main(remote: str) -> bool:
        """True when the remote already carries a brain (a `main` branch)."""
        r = subprocess.run(["git", "ls-remote", "--heads", remote, "main"],
                           capture_output=True, text=True)
        return r.returncode == 0 and bool(r.stdout.strip())

    def clone_if_missing(self) -> None:
        # Audit #20: crashed-clone detection — a half-cloned directory
        # (without .git) blocked every further clone attempt forever.
        if self.path.exists() and (self.path / ".git").exists():
            return
        if not self.remote:
            raise ValueError("No remote given and no clone present.")
        if self.path.exists() and any(self.path.iterdir()) and not (self.path / ".git").exists():
            raise RuntimeError(
                f"{self.path} exists but is not a brain repo (no .git) and "
                "not empty — please inspect/remove it manually instead of overwriting it.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", self.remote, str(self.path)], check=True)

    def init(self, remote: str | None = None, commit: bool = True) -> None:
        """Creates a fresh brain repo at the path (onboarding: `ig init`).

        Sets up the structure (nodes/, edges.jsonl, vectors.jsonl, INDEX.md),
        `git init` + branch main, optionally an origin remote, and commits the
        initial state. Idempotent: an existing repo is not overwritten. Without
        a remote the first commit stays local (push=False).

        If the remote already carries a brain (a `main` branch), it is cloned
        instead of initialized: two machines running `ig init --remote <same
        brain>` used to create two unrelated root commits, so the second push
        was rejected as a non-fast-forward.
        """
        if (self.mode == "git" and remote and not (self.path / ".git").exists()
                and self._remote_has_main(remote)):
            self.remote = remote
            self.clone_if_missing()
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "nodes").mkdir(parents=True, exist_ok=True)
        if not self.edges_file.exists():
            self.write_edges([])
        if not self.vectors_file.exists():
            self.write_vectors({})
        self.rebuild_index()
        if self.mode == "git" and not (self.path / ".git").exists():
            subprocess.run(["git", "-C", str(self.path), "init", "--quiet"], check=True)
            subprocess.run(["git", "-C", str(self.path), "symbolic-ref",
                            "HEAD", "refs/heads/main"], check=True)
            if remote:
                self.remote = remote
                subprocess.run(["git", "-C", str(self.path), "remote", "add",
                                "origin", remote], check=True)
        if commit:
            # With remote → push the initial commit; without → commit locally only.
            self.commit_and_push("init: brain repo created", push=bool(remote))

    def ensure_ready(self) -> None:
        """Make sure the brain repo exists (init or clone).

        Called at the start of every write path so `ig ingest` works
        immediately on a fresh machine without manual setup.
        """
        if self.mode != "git":
            self.path.mkdir(parents=True, exist_ok=True)
            return
        if (self.path / ".git").exists():
            return
        if self.remote:
            self.clone_if_missing()
        else:
            self.init(remote=None, commit=False)

    def pull(self) -> None:
        if self.mode != "git":
            return
        # Without origin (freshly `ig init`-ed, local) pull is a no-op.
        has_origin = subprocess.run(
            ["git", "-C", str(self.path), "remote", "get-url", "origin"],
            capture_output=True).returncode == 0
        if not has_origin:
            return
        # Audit #20: a plain `pull origin main` hangs on a merge conflict or
        # fails hard after a failed push — afterwards every request 500s
        # until manual repair. `--rebase --autostash` stashes local changes,
        # rebases onto origin/main and restores them; only real conflicts
        # remain visible as errors.
        r = subprocess.run(
            ["git", "-C", str(self.path), "pull", "--quiet", "--rebase",
             "--autostash", "origin", "main"],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                "git pull failed (brain repo needs manual attention; "
                "local changes were stashed via autostash):\n"
                + (r.stderr or r.stdout)[-500:])

    def commit_and_push(self, message: str, push: bool = True) -> None:
        if self.mode != "git":
            return
        # Bot identity is configurable (IG_BOT_NAME/IG_BOT_EMAIL); no longer
        # a hard-wired personal identity.
        bot_name = os.environ.get("IG_BOT_NAME", "graph-engine-bot")
        bot_email = os.environ.get("IG_BOT_EMAIL", "bot@graph-engine.local")
        env_user = ["-c", f"user.name={bot_name}", "-c", f"user.email={bot_email}"]
        subprocess.run(["git", "-C", str(self.path), *env_user, "add", "-A"], check=True)
        diff = subprocess.run(["git", "-C", str(self.path), *env_user,
                               "diff", "--cached", "--quiet"], capture_output=True)
        if diff.returncode == 0:
            return  # nothing to commit
        subprocess.run(["git", "-C", str(self.path), *env_user,
                        "commit", "--quiet", "-m", message], check=True)
        if not push:
            return
        # Only push when an origin exists (freshly `ig init`-ed without a
        # remote has none — then the first commit stays local).
        has_origin = subprocess.run(
            ["git", "-C", str(self.path), "remote", "get-url", "origin"],
            capture_output=True).returncode == 0
        if has_origin:
            # Audit #31: a failed push must not look like a failed ingest — the
            # commit is already local and consistent; the next pull --rebase
            # --autostash replays cleanly. Raise a precise, actionable error.
            r = subprocess.run(["git", "-C", str(self.path), "push", "--quiet",
                                "origin", "main"], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(
                    f"git push failed (commit IS local, nothing lost): "
                    f"{(r.stderr or r.stdout).strip()[-300:]}")

    # ---------- Nodes ----------

    def node_path(self, node_id: str) -> Path:
        # Audit #18: node IDs land unverified in paths — a crafted ID with
        # '/'/'..' could escape nodes/ (arbitrary read/write with the
        # .md suffix). The guard is path safety, not the 12-hex convention:
        # short/readable IDs (fixtures, hand-built brains) stay valid;
        # anything that could escape nodes/ or create dotfiles is rejected.
        if (not node_id or "/" in node_id or "\\" in node_id
                or node_id in (".", "..") or node_id.startswith(".")
                or "\x00" in node_id or len(node_id) > 200):
            raise ValueError(f"Invalid node ID: {node_id!r} (path-unsafe)")
        return self.path / "nodes" / f"{node_id}.md"

    def merge_node(self, node: Node, source: str | None = None) -> None:
        """Duplicate ingest: keep the existing node, log the source.

        tags/created stay untouched; the new source is added to the
        frontmatter as a `sources:` list (without duplicates)."""
        sources = list(getattr(node, "sources", []) or [])
        if node.source not in sources:
            sources.insert(0, node.source)
        if source and source not in sources:
            sources.append(source)
        node.sources = sources
        self.write_node(node)

    def write_node(self, node: Node) -> None:
        nodes_dir = self.path / "nodes"
        nodes_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.node_path(node.id), node.to_markdown())

    def promote_node(self, node_id: str) -> Node | None:
        """Dual buffer (V2#2): probation -> active after successful dedup check."""
        node = next((n for n in self.read_nodes() if n.id == node_id), None)
        if node is None:
            return None
        node.status = "active"
        self.write_node(node)
        return node

    def tombstone_node(self, node_id: str) -> Node | None:
        """Graceful degradation (V2#2): mark the node as forgotten (never hard-delete)."""
        node = next((n for n in self.read_nodes() if n.id == node_id), None)
        if node is None:
            return None
        node.status = "tombstone"
        self.write_node(node)
        return node

    def read_nodes(self) -> list[Node]:
        nodes_dir = self.path / "nodes"
        if not nodes_dir.exists():
            return []
        out = []
        for p in sorted(nodes_dir.glob("*.md")):
            try:
                out.append(Node.from_markdown(p.read_text(encoding="utf-8")))
            except (ValueError, KeyError):
                continue  # skip broken files instead of crashing
        return out

    def read_node(self, node_id: str) -> Node | None:
        """Read ONE node by id (report #1): node_path() + from_markdown with
        the same skip-broken tolerance as read_nodes(). A single-node fetch
        must not pay the full read_nodes() glob (0.076 s at live scale)."""
        path = self.node_path(node_id)
        if path is None or not path.exists():
            return None
        try:
            return Node.from_markdown(path.read_text(encoding="utf-8"))
        except (ValueError, KeyError, OSError):
            return None

    # ---------- Embedding-Cache ----------

    @property
    def vectors_file(self) -> Path:
        return self.path / "vectors.jsonl"

    def read_vectors(self) -> dict[str, list[float]]:
        if not self.vectors_file.exists():
            return {}
        out: dict[str, list[float]] = {}
        for line in self.vectors_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            # Audit #17: a corrupt line must not permanently crash the whole
            # store read (read_nodes skips broken files the same way).
            try:
                d = json.loads(line)
                out[d["id"]] = d["vec"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return out

    def write_vectors(self, vectors: dict[str, list[float]]) -> None:
        content = "".join(
            _jsonl_dumps({"id": nid, "vec": vec}) + "\n"
            for nid, vec in sorted(vectors.items()))
        _atomic_write(self.vectors_file, content)

    # Process-wide memo for persist=False reads (report #1): the MCP server is
    # long-lived, but Brain instances are rebuilt per call via runtime.make_brain,
    # so without a memo every search on a cold clone re-embeds ALL nodes
    # (measured 275 s for 1821 nodes on the 2-core VPS — per search). Keyed by
    # (path, vectors.jsonl mtime) so an external cache fill (cron, CLI) or a
    # different brain invalidates it naturally. Bounded to one brain's worth of
    # vectors per path; entries are replaced, never appended unboundedly.
    _VECTOR_MEMO: dict = {}

    def vectors_for(self, node_ids: set[str], embed_fn, batch_fn=None,
                    persist: bool = True) -> dict[str, list[float]]:
        """Vectors from cache; missing ones are computed and — unless
        `persist=False` — stored. Audit #4: reads nodes/vectors ONCE up front
        instead of per missing ID. Audit #60: when batch_fn is provided, all
        missing nodes are embedded in ONE batch call instead of N sequential
        embed_fn calls (sentence-transformers encodes lists natively).
        `persist=False` (report #1) is the strictly read-only path for the MCP
        server: nothing is written to vectors.jsonl (a cold-cache write into
        the private repo would dirty it and churn the cron rebase); results
        are memoized in-process instead so the NEXT search is warm."""
        vec_file = self.path / "vectors.jsonl"
        memo_key = (str(self.path), vec_file.stat().st_mtime_ns if vec_file.exists() else None)
        memo = Brain._VECTOR_MEMO.get(memo_key)
        if memo is not None:
            return {nid: v for nid, v in memo.items() if nid in node_ids}
        nodes = {n.id: n for n in self.read_nodes()}
        cached = self.read_vectors()
        missing = [nid for nid in node_ids if nid not in cached and nid in nodes]
        if missing and batch_fn is not None:
            vecs = batch_fn([nodes[nid].text for nid in missing])
            for nid, vec in zip(missing, vecs):
                cached[nid] = vec
            dirty = True
        else:
            dirty = False
            for nid in node_ids:
                if nid not in cached:
                    node = nodes.get(nid)
                    if node is None:
                        continue
                    cached[nid] = embed_fn(node.text)
                    dirty = True
        if dirty and persist:
            self.write_vectors(cached)
            # after a write the mtime changed — memoize under the NEW key so
            # the next persist=False call hits it
            Brain._VECTOR_MEMO[(str(self.path), vec_file.stat().st_mtime_ns)] = dict(cached)
        elif not persist:
            Brain._VECTOR_MEMO[memo_key] = dict(cached)
        return {nid: v for nid, v in cached.items() if nid in node_ids}

    # ---------- Edges ----------

    @property
    def edges_file(self) -> Path:
        return self.path / "edges.jsonl"

    def read_edges(self, include_rejected: bool = False) -> list[Edge]:
        if not self.edges_file.exists():
            return []
        edges = []
        for line in self.edges_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            # Audit #17: skip-bad-line as in read_nodes — a corrupt line
            # (crash leftover, hand edit) must not make the whole graph API-dead.
            try:
                d = json.loads(line)
                edge = Edge(d["source"], d["target"], d["kind"],
                            d.get("pending", False), d["id"],
                            valid_from=d.get("valid_from"),
                            valid_to=d.get("valid_to"),
                            confidence=d.get("confidence"),
                            invalidated_by=d.get("invalidated_by"),
                            rejected=d.get("rejected", False),
                            origin=d.get("origin"))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if edge.rejected and not include_rejected:
                continue
            edges.append(edge)
        return edges

    def write_edges(self, edges: list[Edge]) -> None:
        content = "".join(_jsonl_dumps(e.to_dict()) + "\n" for e in edges)
        _atomic_write(self.edges_file, content)

    def add_edge(self, edge: Edge) -> None:
        edges = self.read_edges(include_rejected=True)
        edges.append(edge)
        self.write_edges(edges)

    def invalidate_edge(self, edge_id: str, reason: str | None = None,
                        by_edge_id: str | None = None) -> Edge | None:
        """Invalidate the edge instead of deleting it (Zep lesson): valid_to is set,
        the edge stays in the file with its full history. `by_edge_id` records
        the provenance of which edge/event invalidated it (V1#1)."""
        with self._lock:
            edges = self.read_edges(include_rejected=True)
            edge = next((e for e in edges if e.id == edge_id and not e.rejected), None)
            if edge is None or edge.valid_to is not None:
                return None
            edge.valid_to = _now_iso()
            if by_edge_id:
                edge.invalidated_by = by_edge_id
            self.write_edges(edges)
            return edge

    def resolve_edge(self, edge_id: str, accept: bool) -> Edge | None:
        with self._lock:
            edges = self.read_edges(include_rejected=True)
            edge = next((e for e in edges if e.id == edge_id and e.pending and not e.rejected
                         and e.valid_to is None), None)
            if edge is None:
                return None
            edge.pending = False
            edge.rejected = not accept
            self.write_edges(edges)
            return edge

    def restore_edge(self, edge_id: str) -> Edge | None:
        """Return a saved decision to the inbox without reviving invalidated facts."""
        with self._lock:
            edges = self.read_edges(include_rejected=True)
            edge = next((e for e in edges if e.id == edge_id and not e.pending
                         and e.valid_to is None), None)
            if edge is None:
                return None
            edge.pending = True
            edge.rejected = False
            self.write_edges(edges)
            return edge

    # ---------- Graph state for the frontend ----------

    def graph_state(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.read_nodes()],
            "edges": [e.to_dict() for e in self.read_edges()],
        }

    # ---------- Generated table of contents ----------

    def rebuild_index(self) -> None:
        with self._lock:
            lines = ["# Index", "", "| Idea | Source | Created |", "|---|---|---|"]
            for n in self.read_nodes():
                if n.status == "tombstone":
                    continue  # forgotten nodes don't belong in the table of contents
                # Audit #55: truncate to 60 chars FIRST, THEN escape — the
                # other way around the slice can cut a \| escape in half and
                # break the table row.
                title = n.text[:60].replace("|", "\\|")
                lines.append(f"| [{title}](nodes/{n.id}.md) | {n.source} | {n.created} |")
            _atomic_write(self.path / "INDEX.md", "\n".join(lines) + "\n")
