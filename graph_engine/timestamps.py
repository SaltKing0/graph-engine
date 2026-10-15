"""ISO-8601 query timestamps, with timezone-free values interpreted as UTC."""

from datetime import datetime, timezone


def parse_timestamp(value: str) -> datetime:
    """Return an aware UTC instant without changing the stored representation.

    Date-only values mean midnight UTC. Explicit offsets describe the same
    instant after conversion; the host's local timezone is never consulted.
    """
    try:
        if not isinstance(value, str):
            raise ValueError("timestamp must be a string")
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid timestamp: {value!r}") from exc
