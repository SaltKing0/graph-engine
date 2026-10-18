"""Locate JSON fields by full path, preserving exact source coordinates."""
from __future__ import annotations

from decimal import Decimal
import json


def spans(text: str) -> tuple[dict, dict]:
    """Return scalar-value and object-key spans; reject duplicate object keys."""
    def invalid(value: str) -> None:
        raise ValueError('Non-JSON numeric constant: ' + value)

    decoder = json.JSONDecoder(parse_float=Decimal, parse_constant=invalid)
    values, keys = {}, {}

    def space(at: int) -> int:
        while at < len(text) and text[at] in ' \t\r\n':
            at += 1
        return at

    def visit(at: int, path: tuple) -> int:
        at = space(at)
        if at >= len(text):
            raise ValueError('Incomplete JSON')
        if text[at] == '{':
            at = space(at + 1)
            seen = set()
            if text[at:at + 1] == '}':
                return at + 1
            while True:
                if text[at:at + 1] != '"':
                    raise ValueError('Invalid object key')
                key, end = decoder.raw_decode(text, at)
                if key in seen:
                    raise ValueError('Duplicate JSON field: ' + key)
                seen.add(key)
                keys[path + (key,)] = (at + 1, end - 1)
                at = space(end)
                if text[at:at + 1] != ':':
                    raise ValueError('Missing JSON colon')
                at = space(visit(at + 1, path + (key,)))
                if text[at:at + 1] == '}':
                    return at + 1
                if text[at:at + 1] != ',':
                    raise ValueError('Invalid JSON object delimiter')
                at = space(at + 1)
        if text[at] == '[':
            at = space(at + 1)
            index = 0
            if text[at:at + 1] == ']':
                return at + 1
            while True:
                at = space(visit(at, path + (index,)))
                index += 1
                if text[at:at + 1] == ']':
                    return at + 1
                if text[at:at + 1] != ',':
                    raise ValueError('Invalid JSON array delimiter')
                at = space(at + 1)
        _, end = decoder.raw_decode(text, at)
        values[path] = (at + 1, end - 1) if text[at] == '"' else (at, end)
        return end

    if space(visit(0, ())) != len(text):
        raise ValueError('Trailing JSON data')
    return values, keys
