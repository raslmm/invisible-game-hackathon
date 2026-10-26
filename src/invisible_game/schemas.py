"""Versioned, dependency-free contracts for replay events and future insights."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import ClassVar, Mapping

EVENT_SCHEMA_VERSION = "match-event.v1"
INSIGHT_SCHEMA_VERSION = "match-insight.v1"


def _required_text(row: Mapping[str, str | None], field: str) -> str:
    value = row.get(field)
    if value is None or not value.strip():
        raise ValueError(f"Missing required value for {field!r}")
    return value.strip()


def _integer(row: Mapping[str, str | None], field: str) -> int:
    value = _required_text(row, field)
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Expected an integer for {field!r}, got {value!r}") from exc


def _number(row: Mapping[str, str | None], field: str) -> float:
    value = _required_text(row, field)
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"Expected a number for {field!r}, got {value!r}") from exc
    if not isfinite(parsed):
        raise ValueError(f"Expected a finite number for {field!r}, got {value!r}")
    return parsed


def _optional_number(row: Mapping[str, str | None], field: str) -> float | None:
    value = row.get(field)
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"Expected a number for {field!r}, got {value!r}") from exc
    if not isfinite(parsed):
        raise ValueError(f"Expected a finite number for {field!r}, got {value!r}")
    return parsed


def _boolean(row: Mapping[str, str | None], field: str) -> bool:
    value = _required_text(row, field).lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise ValueError(f"Expected a boolean for {field!r}, got {value!r}")


@dataclass(frozen=True, slots=True)
class MatchEvent:
    """One normalized synthetic match event, mapped from data/events.csv."""

    event_id: str
    match_id: str
    timestamp_seconds: int
    minute: int
    period: int
    team_name: str
    player_id: str
    player_position: str
    event_type: str
    outcome: str
    possession_id: str
    x: float
    y: float
    pitch_zone: str
    pitch_lane: str
    pressure_intensity: float
    defenders_behind_ball: int
    recovery_speed_index: float
    fatigue_index: float
    xg: float | None
    is_subject_team: bool
    data_origin: str
    is_dangerous_turnover: bool
    is_attacking_entry: bool

    @classmethod
    def from_csv_row(cls, row: Mapping[str, str | None]) -> MatchEvent:
        """Parse and validate one CSV record using the dataset's column names."""
        return cls(
            event_id=_required_text(row, "event_id"),
            match_id=_required_text(row, "match_id"),
            timestamp_seconds=_integer(row, "timestamp_seconds"),
            minute=_integer(row, "minute"),
            period=_integer(row, "period"),
            team_name=_required_text(row, "team_name"),
            player_id=_required_text(row, "player_id"),
            player_position=_required_text(row, "player_position"),
            event_type=_required_text(row, "event_type"),
            outcome=_required_text(row, "outcome"),
            possession_id=_required_text(row, "possession_id"),
            x=_number(row, "x"),
            y=_number(row, "y"),
            pitch_zone=_required_text(row, "pitch_zone"),
            pitch_lane=_required_text(row, "pitch_lane"),
            pressure_intensity=_number(row, "pressure_intensity"),
            defenders_behind_ball=_integer(row, "defenders_behind_ball"),
            recovery_speed_index=_number(row, "recovery_speed_index"),
            fatigue_index=_number(row, "fatigue_index"),
            xg=_optional_number(row, "xg"),
            is_subject_team=_boolean(row, "is_subject_team"),
            data_origin=_required_text(row, "data_origin"),
            is_dangerous_turnover=_boolean(row, "is_dangerous_turnover"),
            is_attacking_entry=_boolean(row, "is_attacking_entry"),
        )

    def __post_init__(self) -> None:
        if not self.event_id or not self.match_id:
            raise ValueError("event_id and match_id must not be empty")
        if self.timestamp_seconds < 0 or self.minute < 0 or self.period < 1:
            raise ValueError("Event time must be non-negative and period must be at least 1")
        if not 0 <= self.x <= 100 or not 0 <= self.y <= 100:
            raise ValueError("Pitch coordinates x and y must be between 0 and 100")
        for name in ("pressure_intensity", "recovery_speed_index", "fatigue_index"):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.xg is not None and not 0 <= self.xg <= 1:
            raise ValueError("xg must be between 0 and 1 when present")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation of the event fields."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Stable JSONL wrapper that makes event payload versions explicit."""

    sequence: int
    event: MatchEvent

    schema_version: ClassVar[str] = EVENT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "message_type": "match_event",
            "sequence": self.sequence,
            "match_id": self.event.match_id,
            "timestamp_seconds": self.event.timestamp_seconds,
            "event": self.event.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Insight:
    """Evidence-first contract; confidence is rule support, not probability."""

    insight_id: str
    match_id: str
    timestamp_seconds: int
    category: str
    severity: int
    confidence: float
    title: str
    why_it_matters: str
    evidence_event_ids: tuple[str, ...]
    signals: Mapping[str, int | float]

    schema_version: ClassVar[str] = INSIGHT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.insight_id or not self.match_id or not self.category:
            raise ValueError("insight_id, match_id, and category must not be empty")
        if self.timestamp_seconds < 0:
            raise ValueError("Insight timestamp_seconds must be non-negative")
        if not 1 <= self.severity <= 5:
            raise ValueError("Insight severity must be between 1 and 5")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Insight confidence must be between 0 and 1")
        if not self.evidence_event_ids:
            raise ValueError("An insight must cite at least one supporting event")
        if len(set(self.evidence_event_ids)) != len(self.evidence_event_ids):
            raise ValueError("Insight evidence_event_ids must be unique")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation with evidence references intact."""
        return {
            "schema_version": self.schema_version,
            "insight_id": self.insight_id,
            "match_id": self.match_id,
            "timestamp_seconds": self.timestamp_seconds,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "title": self.title,
            "why_it_matters": self.why_it_matters,
            "evidence_event_ids": list(self.evidence_event_ids),
            "signals": dict(self.signals),
        }
