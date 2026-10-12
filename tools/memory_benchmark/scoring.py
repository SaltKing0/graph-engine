"""Transparent deterministic metrics, not a semantic/LLM judge."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def retrieval_metrics(evidence: list[str] | None, retrieved: list[str],
                      included: list[str]) -> dict[str, float | None]:
    if not evidence:
        return {"recall_at_k": None, "mrr": None, "evidence_coverage": None}
    expected = set(evidence)
    rank = next((i for i, nid in enumerate(retrieved, 1) if nid in expected), None)
    return {"recall_at_k": len(expected & set(retrieved)) / len(expected),
            "mrr": 1 / rank if rank else 0.0,
            "evidence_coverage": len(expected & set(included)) / len(expected)}


def validate_answer(answer: dict[str, Any]) -> None:
    if not isinstance(answer, dict):
        raise ValueError("answer must be an object")
    if (not isinstance(answer.get("text"), str)
            or not isinstance(answer.get("abstained"), bool)
            or not isinstance(answer.get("citations"), list)
            or not all(isinstance(nid, str) for nid in answer["citations"])
            or len(answer["citations"]) != len(set(answer["citations"]))):
        raise ValueError("answer needs text, boolean abstained and unique string citations")
    # Prevent a factual answer with an abstention flag from gaming the score.
    if answer["abstained"] and (answer["text"].strip() or answer["citations"]):
        raise ValueError("an abstention must have empty text and citations")
    if "raw_content" in answer and not isinstance(answer["raw_content"], str):
        raise ValueError("raw_content must be a string when supplied")
    usage = answer.get("usage")
    if usage is not None:
        if not isinstance(usage, dict):
            raise ValueError("usage must be an object or null")
        for key in ("prompt_tokens", "completion_tokens"):
            value = usage.get(key)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("actual token usage must be nonnegative integers or null")


def answer_metrics(question: dict[str, Any], answer: dict[str, Any] | None,
                   context_ids: list[str]) -> dict[str, Any]:
    empty = {"answer_correct_exact": None, "abstention_correct": None,
             "false_memory_detected": None, "invalid_citations": None}
    if answer is None:
        return empty
    validate_answer(answer)
    abstained = answer["abstained"]
    text = normalize(answer["text"])
    unanswerable = question["unanswerable"]
    invalid = sorted(set(answer["citations"]) - set(context_ids))
    correct = abstained if unanswerable else (
        not abstained and text in {normalize(ref) for ref in question["answers"]})
    forbidden = text in {normalize(ref) for ref in question.get("forbidden_answers", [])}
    return {"answer_correct_exact": correct,
            "abstention_correct": abstained == unanswerable,
            # A limited, inspectable proxy, never all incorrect free-form answers.
            "false_memory_detected": bool((unanswerable and not abstained) or forbidden or invalid),
            "invalid_citations": invalid}
