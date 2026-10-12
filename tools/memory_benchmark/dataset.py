"""Versioned turn-level datasets; gold annotations never enter retrieval."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_DATASET = Path(__file__).parent / "data" / "de_en_v1.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_dataset(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    dataset = json.loads(raw)
    validate_dataset(dataset)
    return dataset, sha256(raw)


def validate_dataset(dataset: dict[str, Any]) -> None:
    if (not isinstance(dataset, dict) or dataset.get("schema_version") != 1
            or not isinstance(dataset.get("version"), str) or not dataset["version"].strip()):
        raise ValueError("dataset requires schema_version=1 and a pinned version")
    conversations = dataset.get("conversations", [])
    questions = dataset.get("questions", [])
    if (not isinstance(conversations, list) or not isinstance(questions, list)
            or not conversations or not questions
            or not all(isinstance(item, dict) for item in [*conversations, *questions])):
        raise ValueError("dataset needs conversations and questions")
    ids: dict[str, set[str]] = {}
    for conversation in conversations:
        cid = conversation["id"]
        if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", cid) or cid in ids:
            raise ValueError("conversation ids must be unique safe identifiers")
        ids[cid] = set()
        if (not isinstance(conversation["turns"], list) or not conversation["turns"]
                or not all(isinstance(turn, dict) for turn in conversation["turns"])):
            raise ValueError("empty conversation")
        for turn in conversation["turns"]:
            tid = turn["id"]
            if not isinstance(tid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", tid) or tid in ids[cid]:
                raise ValueError("turn ids must be unique safe node identifiers")
            ids[cid].add(tid)
            if (turn["role"] not in ("user", "assistant")
                    or not isinstance(turn["text"], str) or not turn["text"].strip()
                    or not isinstance(turn["date"], str) or not turn["date"].strip()):
                raise ValueError("turn requires role, date and nonempty text")
        relationships = conversation.get("relationships", [])
        if not isinstance(relationships, list):
            raise ValueError("relationships must be a list of source annotations")
        edge_ids: set[str] = set()
        for edge in relationships:
            if (not isinstance(edge, dict) or set(edge) - {"id", "source", "target", "kind", "predicate", "evidence_ids"}
                    or not isinstance(edge.get("id"), str) or not edge["id"] or edge["id"] in edge_ids
                    or edge.get("source") not in ids[cid] or edge.get("target") not in ids[cid]
                    or not isinstance(edge.get("kind"), str) or not edge["kind"]
                    or ("predicate" in edge and not isinstance(edge["predicate"], str))):
                raise ValueError("relationships require unique IDs, known endpoints and a kind")
            evidence = edge.get("evidence_ids", [])
            if (not isinstance(evidence, list) or not all(isinstance(nid, str) for nid in evidence)
                    or not set(evidence) <= ids[cid]):
                raise ValueError("relationship evidence must reference source turns")
            edge_ids.add(edge["id"])
    qids: set[str] = set()
    for question in questions:
        qid = question["id"]
        if not isinstance(qid, str) or not qid.strip() or qid in qids:
            raise ValueError("duplicate question id")
        qids.add(qid)
        cid = question["conversation_id"]
        if (not isinstance(cid, str) or cid not in ids
                or not isinstance(question["question"], str) or not question["question"].strip()):
            raise ValueError("question requires known conversation and nonempty text")
        if (question["language"] not in ("de", "en")
                or not isinstance(question["category"], str) or not question["category"].strip()):
            raise ValueError("question requires DE/EN language and category")
        if not isinstance(question["unanswerable"], bool):
            raise ValueError("unanswerable must be boolean")
        evidence = question["evidence_ids"]
        if evidence is not None and (not isinstance(evidence, list)
                                    or not all(isinstance(nid, str) for nid in evidence)
                                    or len(evidence) != len(set(evidence))
                                    or not set(evidence) <= ids[cid]):
            raise ValueError("evidence ids must reference unique source turns")
        for key in ("answers", "forbidden_answers"):
            values = question.get(key, [])
            if (not isinstance(values, list)
                    or not all(isinstance(value, str) and value.strip() for value in values)):
                raise ValueError(f"{key} must be a list of nonempty reference strings")
        if question["unanswerable"] and (evidence or question["answers"]):
            raise ValueError("unanswerable questions cannot have positive gold evidence/answers")
        if not question["unanswerable"] and not question["answers"]:
            raise ValueError("answerable questions need reference answers")


def source_documents(conversation: dict[str, Any]) -> list[dict[str, str]]:
    """Whole-turn import, identical for all backends; no extraction oracle."""
    return [{"id": turn["id"],
             "text": f"{turn['date']} [{turn['role']}] {turn['text']}"}
            for turn in conversation["turns"]]


def import_longmemeval(path: Path, version: str) -> dict[str, Any]:
    """Import local official-format JSON, using has_answer turn annotations.

    When turn evidence is unavailable, use null (unknown), not all turns in
    an answer session. Original annotations are retained for upstream scoring.
    """
    raw = path.read_bytes()
    samples = json.loads(raw)
    dataset: dict[str, Any] = {
        "schema_version": 1, "version": version,
        "provenance": {"benchmark": "LongMemEval", "source_sha256": sha256(raw),
                       "source_file": path.name, "adapter_version": 1},
        "conversations": [], "questions": [],
    }
    for index, sample in enumerate(samples):
        cid = f"lme-{index}"
        sessions = sample["haystack_sessions"]
        session_ids = sample["haystack_session_ids"]
        dates = sample["haystack_dates"]
        if len(sessions) != len(session_ids) or len(sessions) != len(dates):
            raise ValueError("LongMemEval session ids, dates and sessions must align")
        turns, evidence = [], []
        has_annotations = False
        for si, (session, sid, date) in enumerate(zip(sessions, session_ids, dates)):
            for ti, turn in enumerate(session):
                tid = f"{cid}-s{si}-t{ti}"
                turns.append({"id": tid, "date": date, "role": turn["role"],
                              "text": turn["content"], "upstream_session_id": sid})
                has_annotations |= "has_answer" in turn
                if turn.get("has_answer"):
                    evidence.append(tid)
        unanswerable = str(sample["question_id"]).endswith("_abs")
        dataset["conversations"].append({"id": cid, "turns": turns})
        dataset["questions"].append({
            "id": str(sample["question_id"]), "conversation_id": cid,
            "language": "en", "category": sample["question_type"],
            "question": sample["question"], "question_date": sample["question_date"],
            "unanswerable": unanswerable,
            "answers": [] if unanswerable else [str(sample["answer"])],
            "evidence_ids": [] if unanswerable else evidence if has_annotations else None,
            "forbidden_answers": [], "upstream_answer": sample["answer"],
            "upstream_answer_session_ids": sample["answer_session_ids"],
        })
    validate_dataset(dataset)
    return dataset
