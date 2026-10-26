"""Local, timestamp-ordered replay for the synthetic football event feed."""
from __future__ import annotations

import csv
import time
from math import isfinite
from pathlib import Path
from typing import Callable, Iterable

from .schemas import EventEnvelope, MatchEvent


def load_match_events(
    csv_path: str | Path,
    match_id: str | None = None,
) -> list[MatchEvent]:
    """Load one match and order events by source time, preserving CSV tie order.

    If match_id is omitted, the first match in the file is selected.
    """
    selected_match = match_id
    events: list[tuple[int, MatchEvent]] = []
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise ValueError(f"No CSV header found in {csv_path}")
        required = {"event_id", "match_id", "timestamp_seconds"}
        missing = sorted(required.difference(reader.fieldnames))
        if missing:
            raise ValueError(f"Event CSV is missing required columns: {', '.join(missing)}")

        for row_number, row in enumerate(reader):
            row_match = row.get("match_id")
            if selected_match is None and row_match:
                selected_match = row_match
            if row_match != selected_match:
                continue
            try:
                event = MatchEvent.from_csv_row(row)
            except ValueError as exc:
                line_number = row_number + 2
                raise ValueError(f"{csv_path}:{line_number}: {exc}") from exc
            events.append((row_number, event))

    if selected_match is None:
        raise ValueError(f"No match rows found in {csv_path}")
    if not events:
        raise ValueError(f"No events found for match {selected_match!r} in {csv_path}")

    # Stable tie ordering prevents arbitrary reordering of simultaneous events.
    events.sort(key=lambda item: (item[1].timestamp_seconds, item[0]))
    return [event for _, event in events]


class EventReplay:
    """Replay events with pause/resume/reset, speed control, and idempotency."""

    def __init__(
        self,
        events: Iterable[MatchEvent],
        *,
        speed: float = 60.0,
        realtime: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        ordered = list(enumerate(events))
        ordered.sort(key=lambda item: (item[1].timestamp_seconds, item[0]))
        self._events = [event for _, event in ordered]
        if not self._events:
            raise ValueError("Replay requires at least one event")
        self._sleep = sleep
        self._realtime = realtime
        self._paused = False
        self._cursor = 0
        self._sequence = 0
        self._seen_event_ids: set[str] = set()
        self._duplicates_skipped = 0
        self._last_timestamp: int | None = None
        self.set_speed(speed)

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def finished(self) -> bool:
        return self._cursor >= len(self._events)

    @property
    def duplicates_skipped(self) -> int:
        return self._duplicates_skipped

    @property
    def speed(self) -> float:
        return self._speed

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        return self._paused

    def set_speed(self, speed: float) -> None:
        """Set replay speed as a positive multiple of source match time."""
        if not isfinite(speed) or speed <= 0:
            raise ValueError("Replay speed must be greater than zero")
        self._speed = float(speed)

    def reset(self) -> None:
        """Restart the selected match and clear per-run deduplication state."""
        self._cursor = 0
        self._sequence = 0
        self._seen_event_ids.clear()
        self._duplicates_skipped = 0
        self._last_timestamp = None
        self._paused = False

    def next_envelope(self) -> EventEnvelope | None:
        """Return the next unique event, or None when paused or finished."""
        if self._paused:
            return None

        while self._cursor < len(self._events):
            event = self._events[self._cursor]
            self._cursor += 1
            if event.event_id in self._seen_event_ids:
                self._duplicates_skipped += 1
                continue

            if self._last_timestamp is not None and self._realtime:
                elapsed = max(0, event.timestamp_seconds - self._last_timestamp)
                delay = elapsed / self._speed
                if delay:
                    self._sleep(delay)

            self._seen_event_ids.add(event.event_id)
            self._last_timestamp = event.timestamp_seconds
            self._sequence += 1
            return EventEnvelope(sequence=self._sequence, event=event)

        return None
