"""Local, append-only document capture with deterministic provenance receipts."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .brain import Brain
    from .brain_engine import BrainEngine

SUPPORTED = {".md", ".txt", ".pdf"}
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 1000
MAX_PAGES = 1000
MAX_TEXT_CHARS = 10_000_000
MAX_CHUNKS = 10_000


class ImportProblem(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_provenance(value: dict) -> None:
    """Validate persisted metadata, including on reads of hand-edited nodes."""
    keys = {"version", "source_id", "content_sha256", "chunk_index", "chunk_count",
            "chunk_chars", "page", "char_start", "char_end", "line_start", "line_end", "parser"}
    if not isinstance(value, dict) or set(value) != keys or value["version"] != 1:
        raise ValueError("Invalid document provenance")
    if (not isinstance(value["source_id"], str) or not value["source_id"].strip()
            or len(value["source_id"]) > 2048
            or not isinstance(value["parser"], str)
            or not isinstance(value["content_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["content_sha256"])):
        raise ValueError("Invalid document source/hash")
    for key in ("chunk_index", "chunk_count", "chunk_chars", "char_start", "char_end", "line_start", "line_end"):
        if type(value[key]) is not int or value[key] < (0 if key == "char_start" else 1):
            raise ValueError("Invalid document location")
    if (value["chunk_index"] > value["chunk_count"] or value["char_end"] <= value["char_start"]
            or value["line_end"] < value["line_start"]
            or value["page"] is not None and (type(value["page"]) is not int or value["page"] < 1)):
        raise ValueError("Invalid document location")


@dataclass(frozen=True)
class Chunk:
    text: str
    page: int | None
    start: int
    end: int
    line_start: int
    line_end: int


def chunk_text(text: str, limit: int, page: int | None = None) -> list[Chunk]:
    """Prefer paragraph/heading boundaries, then lines/words, with a hard char cap.

    Offsets are zero-based, end-exclusive Unicode character offsets into the
    decoded text (or a PDF page's extracted text). Line numbers are one-based.
    Boundary whitespace is omitted; every non-whitespace character survives.
    """
    if not 1 <= limit <= 20_000:
        raise ValueError("chunk_chars must be between 1 and 20000")
    boundaries = re.finditer(r"\n[ \t\r]*\n|\n(?=#{1,6}[ \t])", text)
    boundary = next(boundaries, None)
    result: list[Chunk] = []
    start = 0
    line, counted_to = 1, 0
    while start < len(text):
        while start < len(text) and text[start].isspace():
            start += 1
        if start == len(text):
            break
        end = min(start + limit, len(text))
        if end < len(text):
            preferred = None
            while boundary is not None and boundary.end() <= end:
                if boundary.end() > start:
                    preferred = boundary.end()
                boundary = next(boundaries, None)
            if preferred is not None:
                end = preferred
            else:
                newline = text.rfind("\n", start + 1, end + 1)
                space = text.rfind(" ", start + 1, end + 1)
                if newline > start:
                    end = newline
                elif space > start:
                    end = space
        trimmed_end = end
        while trimmed_end > start and text[trimmed_end - 1].isspace():
            trimmed_end -= 1
        line += text.count("\n", counted_to, start)
        line_end = line + text.count("\n", start, trimmed_end)
        result.append(Chunk(text[start:trimmed_end], page, start, trimmed_end, line, line_end))
        counted_to = start
        start = end
        if len(result) > MAX_CHUNKS:
            raise ImportProblem("too_many_chunks", f"Document exceeds {MAX_CHUNKS} chunks")
    return result


def _read_chunks(path: Path, max_bytes: int, chunk_chars: int) -> tuple[str, str, list[Chunk]]:
    # Bound the read itself, not just a stat that can race with a growing file.
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ImportProblem("not_regular_file", "Only regular local files are supported")
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ImportProblem("file_too_large", f"File exceeds {max_bytes} bytes")
    digest = hashlib.sha256(data).hexdigest()
    if path.suffix.lower() != ".pdf":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ImportProblem("invalid_utf8", "Text files must be UTF-8") from exc
        return digest, "utf8-v1", chunk_text(text, chunk_chars)
    try:
        import pypdf
    except ImportError as exc:
        raise ImportProblem("pdf_extra_missing", 'PDF import requires pip install "graph-engine-memory[pdf]"') from exc
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ImportProblem("encrypted_pdf", "Encrypted PDFs are unsupported; provide an unencrypted local copy")
        if len(reader.pages) > MAX_PAGES:
            raise ImportProblem("too_many_pages", f"PDF exceeds {MAX_PAGES} pages")
        chunks: list[Chunk] = []
        characters = 0
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            characters += len(text)
            if characters > MAX_TEXT_CHARS:
                raise ImportProblem("extracted_text_too_large", "PDF extracted text exceeds the character limit")
            chunks.extend(chunk_text(text, chunk_chars, number))
            if len(chunks) > MAX_CHUNKS:
                raise ImportProblem("too_many_chunks", f"PDF exceeds {MAX_CHUNKS} chunks")
        return digest, f"pypdf-{pypdf.__version__}", chunks
    except ImportProblem:
        raise
    except Exception as exc:
        raise ImportProblem("malformed_pdf", "PDF could not be parsed or its text extracted") from exc


def _selected_paths(paths: Iterable[str | Path], recursive: bool) -> list[tuple[Path, str | None]]:
    """Never follow directory/file symlinks; bound discovery before any writes."""
    result: dict[Path, str | None] = {}
    visited_directories = 0

    def add(path: Path, error: str | None = None) -> None:
        path = path.absolute()
        result[path] = error
        if len(result) > MAX_FILES:
            raise ValueError(f"Selection exceeds {MAX_FILES} entries; select smaller directories")

    for selected in paths:
        root = Path(selected).expanduser().absolute()
        if root.is_symlink():
            add(root, "symbolic_link")
        elif root.is_dir():
            def onerror(exc: OSError) -> None:
                add(Path(exc.filename or root), "unreadable_directory")
            for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
                visited_directories += 1
                if visited_directories > MAX_FILES:
                    raise ValueError(f"Selection exceeds {MAX_FILES} directories; select smaller directories")
                dirs.sort()
                for name in dirs[:]:
                    child = Path(directory) / name
                    if child.is_symlink():
                        add(child, "symbolic_link")
                        dirs.remove(name)
                for name in sorted(files):
                    file = Path(directory) / name
                    add(file, "symbolic_link" if file.is_symlink() else None)
                if not recursive:
                    break
        elif not root.exists():
            add(root, "missing_path")
        elif not root.is_file():
            add(root, "not_regular_file")
        else:
            add(root)
    return sorted(result.items(), key=lambda item: str(item[0]))


def import_documents(brain: Brain, paths: Iterable[str | Path], *,
                     extensions: Iterable[str] = (".md", ".txt"), recursive: bool = False,
                     max_bytes: int = DEFAULT_MAX_BYTES, chunk_chars: int = 2000,
                     source_id: str | None = None, source_prefix: str | None = None,
                     dry_run: bool = False, engine: BrainEngine | None = None,
                     extraction: str | None = None) -> dict:
    """Capture per chunk, then optionally extract in a second commit.

    Receipts are append-only and keyed by source, raw-file hash, chunk settings,
    parser version and location. Never overwrite edits, revive tombstones or
    delete obsolete versions. Completed chunks survive per-file failures.
    """
    from .brain import Node
    from .entities import command_extractor

    paths = list(paths)
    if not paths:
        raise ValueError("Select at least one local file or directory")
    extensions = {"." + ext.lower().lstrip(".") for ext in extensions}
    if not extensions or extensions - SUPPORTED:
        raise ValueError("Select supported extensions: .md, .txt, .pdf")
    if not 1 <= max_bytes <= 100 * 1024 * 1024 or not 1 <= chunk_chars <= 20_000:
        raise ValueError("max_bytes must be 1..104857600 and chunk_chars 1..20000")
    if extraction not in (None, "rules", "model"):
        raise ValueError("extraction must be rules or model")
    if extraction and engine is None and not dry_run:
        raise ValueError("Extraction requires the ingestion engine")
    if engine is not None and engine.brain is not brain:
        raise ValueError("The ingestion engine must use the selected brain")
    if source_id is not None and source_prefix is not None:
        raise ValueError("Choose source_id or source_prefix")
    if source_id is not None and (len(paths) != 1 or Path(paths[0]).expanduser().is_dir()):
        raise ValueError("source_id requires exactly one selected file")
    for identifier in (source_id, source_prefix):
        if identifier is not None and (not identifier.strip() or len(identifier) > 1800):
            raise ValueError("Source identifier must be non-empty and at most 1800 characters")
    selected = _selected_paths(paths, recursive)
    # A prefix replaces absolute paths with names relative to one selection root.
    if source_prefix is not None and len(paths) != 1:
        raise ValueError("source_prefix requires one file or directory selection")
    root = Path(paths[0]).expanduser().absolute()
    base = root if root.is_dir() else root.parent
    extractor = command_extractor() if extraction == "model" and not dry_run else None
    brain.authorize("read" if dry_run else "write")
    files: list[dict] = []
    for path, path_error in selected:
        row: dict = dict(path=str(path), status="failed", chunks=[])
        files.append(row)
        if path_error:
            row.update(error=path_error)
            continue
        if path.suffix.lower() not in extensions:
            row.update(status="skipped", error="extension_not_selected")
            continue
        identifier = source_id if source_id is not None else (
            source_prefix.rstrip("/") + "/" + path.relative_to(base).as_posix()
            if source_prefix is not None else path.resolve().as_uri())
        row["source_id"] = identifier
        try:
            digest, parser, chunks = _read_chunks(path, max_bytes, chunk_chars)
            row.update(content_sha256=digest, chunk_count=len(chunks))
            with nullcontext() if dry_run else brain.write_guard():
                if not dry_run and chunks:
                    brain.ensure_ready()
                    brain.pull()
                for index, chunk in enumerate(chunks, 1):
                    provenance = dict(version=1, source_id=identifier, content_sha256=digest,
                        chunk_index=index, chunk_count=len(chunks), chunk_chars=chunk_chars,
                        parser=parser, page=chunk.page, char_start=chunk.start, char_end=chunk.end,
                        line_start=chunk.line_start, line_end=chunk.line_end)
                    validate_provenance(provenance)
                    key = hashlib.sha256(json.dumps(provenance, sort_keys=True,
                        ensure_ascii=True).encode()).hexdigest()
                    nid = "doc-" + key[:32]
                    brain.authorize("read" if dry_run else "write", nid)
                    existing = brain.read_node(nid)
                    stored_path = brain.node_path(nid)
                    if existing is None and (stored_path.exists() or stored_path.is_symlink()):
                        raise ImportProblem("receipt_unreadable", "Existing receipt cannot be read; refusing overwrite")
                    receipt: dict = dict(node_id=nid, provenance=provenance)
                    row["chunks"].append(receipt)
                    if existing is not None:
                        if existing.document != provenance:
                            raise ImportProblem("receipt_conflict", "Receipt ID belongs to different metadata; refusing overwrite")
                        receipt.update(status="tombstone" if existing.status == "tombstone" else "reused",
                            edited=existing.text != chunk.text.strip())
                    elif dry_run:
                        receipt["status"] = "planned"
                    elif engine is not None:
                        node, _, duplicate = engine.ingest(chunk.text, source="document",
                            _capture_input=chunk.text, _document=provenance, _node_id=nid)
                        receipt.update(status="created", duplicate=duplicate, survivor_id=node.id)
                        existing = brain.read_node(nid)
                    else:
                        existing = Node(chunk.text.strip(), id=nid, source="document", document=provenance,
                            capture=dict(input=chunk.text, node_id=nid, duplicate=False, source="document"))
                        brain.write_node(existing)
                        receipt["status"] = "created"
                        brain.rebuild_index()
                        brain.commit_and_push(f"import document chunk: {nid}")
                    if not dry_run and existing is not None:
                        survivor_id = existing.capture["node_id"] if existing.capture else existing.id
                        receipt["survivor_id"] = survivor_id
                        survivor = brain.read_node(survivor_id)
                        if existing.status == "tombstone" or survivor is None or survivor.status == "tombstone":
                            receipt["status"] = "tombstone"
                            continue
                        # Finish a prior failed commit without rewriting any note.
                        if receipt["status"] == "reused":
                            brain.commit_and_push(f"import receipt: {nid}", sync_pending=True)
                        if extraction:
                            try:
                                extracted = engine.entities(node_id=nid, extractor=extractor)
                                receipt["extraction"] = dict(status="complete",
                                    created_entities=extracted["created_entities"],
                                    created_facts=extracted["created_facts"],
                                    pending_facts=sum(f["pending"] for f in extracted["facts"]))
                            except Exception as exc:
                                receipt["extraction"] = dict(status="failed", retryable=True,
                                    error="access_denied" if isinstance(exc, PermissionError) else "extraction_failed")
                                raise ImportProblem("extraction_failed", "Capture retained; retry to complete extraction") from exc
                row["status"] = "dry_run" if dry_run else "complete" if chunks else "empty"
        except Exception as exc:
            # Ingestion may fail after writing its receipt (e.g. Git commit).
            # Report durable capture rather than implying no data was saved.
            if row["chunks"] and "status" not in row["chunks"][-1] and not dry_run:
                last = row["chunks"][-1]
                try:
                    saved = brain.read_node(last["node_id"])
                    if saved is not None and saved.document == last["provenance"]:
                        last["status"] = "created"
                except (OSError, ValueError):
                    pass
            row.update(status="partial" if any(c.get("status") in ("created", "reused") for c in row["chunks"]) else "failed",
                       error=exc.code if isinstance(exc, ImportProblem) else "access_denied" if isinstance(exc, PermissionError) else "unreadable_file" if isinstance(exc, OSError) else "import_failed",
                       message=str(exc))
    return dict(dry_run=dry_run, files=files,
                failed_files=sum(f["status"] in ("failed", "partial") for f in files),
                created_chunks=sum(c.get("status") == "created" for f in files for c in f["chunks"]),
                reused_chunks=sum(c.get("status") == "reused" for f in files for c in f["chunks"]))
