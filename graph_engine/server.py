"""FastAPI server on top of the Brain (private git repo as storage).

Env control:
  IG_BRAIN_PATH   — path to the brain clone (default: ~/graph-engine-brain)
  IG_BRAIN_REMOTE — SSH/GitHub URL (only used for `git clone` on first
                    setup; no personal default, existing clones keep
                    their own origin)
  IG_BRAIN_MODE   — "git" (real repo) or "local" (FS only, for tests)
  IDEAGRAPH_EMBEDDER — "st" (sentence-transformers) or "hash" (demo/tests)
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import runtime, access, namespaces
from .write_guard import BrainWriteTimeout
from .brain_engine import IngestPartialError
from .decision_memory import RecordPublished
from .decision_schema import RecordConflict
from .decision_service import DecisionService

# Shipped UI assets live INSIDE the package so a pip install serves them too
# (repo-root docs/ would not exist in site-packages).
DOCS_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="GraphEngine")
NO_CACHE = {"Cache-Control": "no-store"}


@app.exception_handler(RecordConflict)
async def decision_conflict_handler(_request: Request, exc: RecordConflict) -> JSONResponse:
    return JSONResponse({'error': str(exc)}, status_code=409, headers={'Cache-Control': 'no-store'})


@app.exception_handler(RecordPublished)
async def decision_published_handler(_request: Request, exc: RecordPublished) -> JSONResponse:
    return JSONResponse({'error': str(exc), 'published_locally': True, 'receipt': exc.receipt},
                        status_code=502, headers={'Cache-Control': 'no-store'})


def _decision_service() -> DecisionService:
    return DecisionService(runtime.make_brain())


async def _decision_body(request: Request) -> dict:
    from .decision_schema import MAX_BYTES, RecordError
    from .decision_service import load_envelope
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise RecordError('Envelope exceeds 64 MiB')
        chunks.append(chunk)
    try:
        return load_envelope(b''.join(chunks).decode('utf-8'))
    except UnicodeError as exc:
        raise RecordError('Invalid UTF-8 envelope') from exc


@app.get('/api/decision-memory/preview')
def decision_preview() -> JSONResponse:
    return JSONResponse(_decision_service().preview(), headers=NO_CACHE)


@app.get('/api/decision-memory/pending')
def decision_pending() -> JSONResponse:
    return JSONResponse(_decision_service().pending(), headers=NO_CACHE)


@app.get('/api/decision-memory/sources/{node_id}')
def decision_source(node_id: str) -> JSONResponse:
    return JSONResponse(_decision_service().source(node_id), headers=NO_CACHE)


@app.post('/api/decision-memory/inspect')
async def decision_inspect(request: Request) -> JSONResponse:
    reference = await _decision_body(request)
    return JSONResponse(await run_in_threadpool(lambda: _decision_service().inspect(reference)), headers=NO_CACHE)


@app.post('/api/decision-memory/result-draft')
async def decision_result_draft(request: Request) -> JSONResponse:
    envelope = await _decision_body(request)
    return JSONResponse(await run_in_threadpool(lambda: _decision_service().result_draft(envelope)), headers=NO_CACHE)


async def _decision_submit(request: Request, schema: str, dry_run: bool) -> JSONResponse:
    from .decision_schema import need
    envelope = await _decision_body(request)
    need(envelope.get('schema') == schema, 'Unexpected envelope schema for this endpoint')
    result = await run_in_threadpool(lambda: _decision_service().submit(envelope, dry_run=dry_run))
    return JSONResponse(result, headers=NO_CACHE)


@app.post('/api/decision-memory/proposals')
async def decision_proposal(request: Request, dry_run: bool = False) -> JSONResponse:
    from .decision_service import PROPOSAL
    return await _decision_submit(request, PROPOSAL, dry_run)


@app.post('/api/decision-memory/reviews')
async def decision_review(request: Request, dry_run: bool = False) -> JSONResponse:
    from .decision_service import REVIEW
    return await _decision_submit(request, REVIEW, dry_run)


@app.exception_handler(BrainWriteTimeout)
async def writer_busy_handler(_request, _exc: BrainWriteTimeout):
    return JSONResponse({"error": "Brain writer busy; retry after the current writer finishes"},
                        status_code=503, headers={**NO_CACHE, "Retry-After": "1"})


@app.middleware("http")
async def access_control(request, call_next):
    # Pin selection before any awaits: switching the CLI while an ingest runs
    # must not send the old graph's payload to the new graph's subscribers.
    graph_token = namespaces.request_graph.set(namespaces.selected())
    identity_token = None
    try:
        if access.policy_path():
            try:
                identity = access.token_principal(request.headers.get("authorization", ""))
            except PermissionError:
                access.audit("http", "", "authenticate", False)
                return JSONResponse({"error": "Authentication required"}, status_code=401, headers=NO_CACHE)
            identity_token = access.request_principal.set(identity)
        return await call_next(request)
    finally:
        if identity_token is not None:
            access.request_principal.reset(identity_token)
        namespaces.request_graph.reset(graph_token)


@app.exception_handler(PermissionError)
async def permission_error_handler(_request, _exc):
    return JSONResponse({"error": "Access denied"}, status_code=403, headers=NO_CACHE)



class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self.graphs: dict[WebSocket, str] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        self.graphs[ws] = runtime.brain_path()

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        self.graphs.pop(ws, None)

    async def broadcast(self, message: dict):
        if access.policy_path():
            return  # protected realtime transport is intentionally disabled
        for ws in list(self.active):
            if self.graphs.get(ws) != runtime.brain_path():
                continue
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


@app.get("/")
def index():
    return FileResponse(DOCS_DIR / "index.html", headers=NO_CACHE)


@app.get("/app.js")
def app_js():
    return FileResponse(DOCS_DIR / "app.js", headers=NO_CACHE)


@app.get("/review")
def review():
    return FileResponse(DOCS_DIR / "review.html", headers=NO_CACHE)


@app.get("/review.js")
def review_js():
    return FileResponse(DOCS_DIR / "review.js", headers=NO_CACHE)


@app.get("/api/graph")
def graph():
    return JSONResponse(runtime.make_brain().graph_state())


def _search_query(query: str) -> str:
    query = query.strip()
    if not query:
        raise ValueError("query must be non-empty")
    return query


@app.get("/api/search")
def search(query: str = Query(min_length=1, max_length=500),
           k: int = Query(default=12, ge=1, le=20),
           graph_hops: int = Query(default=0, ge=0, le=3),
           focal_id: str | None = Query(default=None, min_length=1, max_length=200)):
    """Rank accessible live nodes; RRF scores are not factual confidence.

    Sync handlers run model construction and retrieval in FastAPI's threadpool.
    The secured brain enforces node ACLs and forbids vector-cache writes;
    recall.record additionally filters out nodes the caller cannot write.
    """
    from .retrieval import retrieve_with_evidence
    from .graph_retrieval import graph_options
    query = _search_query(query)
    engine = runtime.make_engine()
    options = graph_options(graph_hops, focal_id)
    response = retrieve_with_evidence(engine, query, k=k,
        persist=not bool(access.policy_path()) if options is None else False,
        track=options is None, graph=options)
    hits = response["hits"]
    live = {node.id: node for node in engine.brain.read_nodes() if node.status != "tombstone"}
    results = []
    for nid, score in hits:
        node = live.get(nid)
        if node is None:
            continue
        # Plain text, never HTML; the browser must render/escape it as text.
        snippet = " ".join(node.text.split())
        if len(snippet) > 200:
            snippet = snippet[:199] + "…"
        results.append({"id": nid, "snippet": snippet, "rank": len(results) + 1,
                        "score": float(score),
                        "score_kind": "rrf_graph" if response["graph"]["graph_used_for_ranking"] else "rrf",
                        **({"graph_evidence": response["evidence"][nid]} if options else {})})
    return JSONResponse({"query": query, "k": k, "results": results,
                         "score_note": ("Relevance scores are not factual confidence; graph paths do not imply facts."
                                        if options else "RRF scores rank relevance, not factual confidence."),
                         **({"graph": response["graph"]} if options else {})},
                        headers=NO_CACHE)


@app.get("/api/search/{node_id}/explain")
def search_explanation(node_id: str, query: str = Query(min_length=1, max_length=500),
                       k: int = Query(default=12, ge=1, le=20),
                       graph_hops: int = Query(default=0, ge=0, le=3),
                       focal_id: str | None = Query(default=None, min_length=1, max_length=200)):
    """Recompute one explanation on demand, without cache or recall writes."""
    from .retrieval import explain
    from .graph_retrieval import graph_options
    query = _search_query(query)
    engine = runtime.make_engine()
    node = engine.brain.read_node(node_id)  # checks the node ACL, including direct requests
    if node is None or node.status == "tombstone":
        return JSONResponse({"error": "Idea unavailable"}, status_code=404, headers=NO_CACHE)
    return JSONResponse(explain(engine, node_id, query, k=k,
                                graph=graph_options(graph_hops, focal_id)), headers=NO_CACHE)


@app.get("/report")
def report_page():
    return FileResponse(DOCS_DIR / "report.html", headers=NO_CACHE)


@app.get("/report.js")
def report_js():
    return FileResponse(DOCS_DIR / "report.js", headers=NO_CACHE)


@app.get("/api/report")
def api_report(since: str | None = None, top: int = 5):
    """Read-only BRAIN_REPORT digest (report #7). Never mutates the brain."""
    from .report import report_data, render_report
    brain = runtime.make_brain()
    try:
        data = report_data(brain, since=since, top=top)
        data["markdown"] = render_report(brain, since=since, top=top)
        return JSONResponse(data)
    finally:
        if hasattr(brain, "close"):
            brain.close()


class IngestBody(BaseModel):
    text: str
    source: str = "human"
    tags: list[str] = []
    allow_duplicates: bool = False
    extraction: str | None = None
    accept_facts: bool = False


@app.exception_handler(ValueError)
async def value_error_handler(_req, exc: ValueError):
    """Audit #57: engine ValueErrors (e.g. empty ingest text) are client errors,
    not 500s — return a clean 400 with the message."""
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": str(exc)}, status_code=400, headers=NO_CACHE)


@app.exception_handler(IngestPartialError)
async def ingest_partial_handler(_req, exc: IngestPartialError):
    return JSONResponse(exc.to_dict(), status_code=502)


@app.post("/api/ingest")
async def ingest(body: IngestBody):
    # Factory calls hash local model files and may load a reranker. Keep that
    # work, as well as Git synchronization and inference, in the threadpool.
    engine = await run_in_threadpool(runtime.make_engine)
    node, edges, is_dup, extracted = await run_in_threadpool(
        engine.capture, body.text, body.source, body.tags,
        body.allow_duplicates, extraction=body.extraction, accept_facts=body.accept_facts)
    await manager.broadcast({
        "type": "ingested",
        "node": node.to_dict(),
        "edges": [e.to_dict() for e in edges],
        "duplicate": is_dup,
    })
    result = {"node": node.to_dict(), "suggested": [e.to_dict() for e in edges],
              "duplicate": is_dup}
    if extracted is not None:
        result["extraction"] = extracted
        if extracted["status"] == "failed":
            return JSONResponse(result, status_code=502)
    return result


@app.post("/api/edge/{edge_id}/accept")
async def accept_edge(edge_id: str):
    engine = await run_in_threadpool(runtime.make_engine)
    edge = await run_in_threadpool(engine.resolve, edge_id, True)
    if edge is None:
        return JSONResponse({"error": "edge not found or not pending"}, status_code=404)
    await manager.broadcast({"type": "edge_resolved", "edge": edge.to_dict(), "accepted": True})
    return edge.to_dict()


@app.post("/api/edge/{edge_id}/reject")
async def reject_edge(edge_id: str):
    engine = await run_in_threadpool(runtime.make_engine)
    edge = await run_in_threadpool(engine.resolve, edge_id, False)
    if edge is None:
        return JSONResponse({"error": "edge not found or not pending"}, status_code=404)
    await manager.broadcast({"type": "edge_resolved", "edge": edge.to_dict(), "accepted": False})
    return {"rejected": edge_id}


class LinkBody(BaseModel):
    source: str
    target: str
    kind: str = "same_as"


@app.post("/api/edge")
async def link_edge(body: LinkBody):
    def _link():
        try:
            return runtime.make_engine().link(body.source, body.target, body.kind), None
        except ValueError as exc:
            return None, str(exc)
    edge, err = await run_in_threadpool(_link)
    if err is not None or edge is None:
        return JSONResponse({"error": err or "link failed"}, status_code=400)
    await manager.broadcast({"type": "edge_linked", "edge": edge.to_dict()})
    return edge.to_dict()


def _http_origin(value: str) -> tuple[str, str, int] | None:
    """Parse a single HTTP origin, rejecting opaque or malformed values."""
    # urlsplit strips some control characters; reject them before parsing.
    if not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username is not None or parts.password is not None
                or value != f"{parts.scheme}://{parts.netloc}"
                or "\\" in parts.netloc or parts.netloc.endswith(":")):
            return None
        port = parts.port
        return parts.scheme, parts.hostname, port if port is not None else (
            443 if parts.scheme == "https" else 80)
    except ValueError:
        return None


def _websocket_origin_allowed(ws: WebSocket) -> bool:
    """Browser sockets must match the request origin; native clients may omit it."""
    origins = ws.headers.getlist("origin")
    if not origins:
        return True
    hosts = ws.headers.getlist("host")
    socket_scheme = ws.scope.get("scheme")
    if len(origins) != 1 or len(hosts) != 1 or socket_scheme not in {"ws", "wss"}:
        return False
    origin = _http_origin(origins[0])
    scheme = "https" if socket_scheme == "wss" else "http"
    return origin is not None and origin == _http_origin(f"{scheme}://{hosts[0]}")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if access.policy_path() or not _websocket_origin_allowed(ws):
        await ws.close(code=1008)
        return
    await manager.connect(ws)
    try:
        while True:
            # Audit #29: catching only WebSocketDisconnect left zombies behind
            # (binary frame → KeyError, TCP reset → RuntimeError) — the socket
            # stayed in manager.active forever and was never closed.
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
        try:
            await ws.close()
        except Exception:
            pass


@app.post("/api/edge/{edge_id}/undo")
async def undo_edge(edge_id: str):
    engine = await run_in_threadpool(runtime.make_engine)
    edge = await run_in_threadpool(engine.undo, edge_id)
    if edge is None:
        return JSONResponse({"error": "edge not found or already resolved"}, status_code=409)
    await manager.broadcast({"type": "edge_restored", "edge": edge.to_dict()})
    return edge.to_dict()
