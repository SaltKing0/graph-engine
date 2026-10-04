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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import runtime, access, namespaces

# Shipped UI assets live INSIDE the package so a pip install serves them too
# (repo-root docs/ would not exist in site-packages).
DOCS_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="GraphEngine")


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
                return JSONResponse({"error": "Authentication required"}, status_code=401)
            identity_token = access.request_principal.set(identity)
        return await call_next(request)
    finally:
        if identity_token is not None:
            access.request_principal.reset(identity_token)
        namespaces.request_graph.reset(graph_token)


@app.exception_handler(PermissionError)
async def permission_error_handler(_request, _exc):
    return JSONResponse({"error": "Access denied"}, status_code=403)



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


NO_CACHE = {"Cache-Control": "no-store"}


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


@app.exception_handler(ValueError)
async def value_error_handler(_req, exc: ValueError):
    """Audit #57: engine ValueErrors (e.g. empty ingest text) are client errors,
    not 500s — return a clean 400 with the message."""
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/ingest")
async def ingest(body: IngestBody):
    # Audit #16: git pull/push + embedding inference are blocking I/O — they
    # run in the threadpool, not on the event loop (otherwise a slow ingest
    # stalls all requests and WS broadcasts).
    engine = runtime.make_engine()
    node, edges, is_dup = await run_in_threadpool(
        engine.ingest, body.text, body.source, body.tags,
        body.allow_duplicates)
    await manager.broadcast({
        "type": "ingested",
        "node": node.to_dict(),
        "edges": [e.to_dict() for e in edges],
        "duplicate": is_dup,
    })
    return {"node": node.to_dict(), "suggested": [e.to_dict() for e in edges],
            "duplicate": is_dup}


@app.post("/api/edge/{edge_id}/accept")
async def accept_edge(edge_id: str):
    edge = await run_in_threadpool(runtime.make_engine().resolve, edge_id, True)
    if edge is None:
        return JSONResponse({"error": "edge not found or not pending"}, status_code=404)
    await manager.broadcast({"type": "edge_resolved", "edge": edge.to_dict(), "accepted": True})
    return edge.to_dict()


@app.post("/api/edge/{edge_id}/reject")
async def reject_edge(edge_id: str):
    edge = await run_in_threadpool(runtime.make_engine().resolve, edge_id, False)
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


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if access.policy_path():
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
    edge = await run_in_threadpool(runtime.make_engine().undo, edge_id)
    if edge is None:
        return JSONResponse({"error": "edge not found or already resolved"}, status_code=409)
    await manager.broadcast({"type": "edge_restored", "edge": edge.to_dict()})
    return edge.to_dict()
